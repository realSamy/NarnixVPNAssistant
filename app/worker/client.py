import json
import logging

import httpx

from app.core.security import SIGNATURE_HEADER, sign_payload

logger = logging.getLogger(__name__)


class WorkerError(Exception):
    """Raised when a callback could not be delivered after every attempt."""


class WorkerClient:
    """Signed HTTP calls to the Worker's `/ai/callback` endpoint.

    This is the backend's half of the bidirectional protocol: the agent never
    talks to Telegram directly — it hands results here, and the Worker owns
    everything user-facing (topics, keyboards, i18n). Keeping this boundary
    strict is what lets the Worker change its UI without touching the agent,
    and the agent without touching the Worker.

    Every request is HMAC-signed the same way inbound ones are verified, so
    the Worker treats this backend as the only caller of the endpoint.
    """

    def __init__(self, http: httpx.AsyncClient, callback_url: str, secret: str, retries: int = 3):
        self._http = http
        self._callback_url = callback_url
        self._secret = secret
        self._retries = max(1, retries)

    async def call(self, payload: dict) -> dict:
        """POSTs one callback, retrying transient failures with backoff.

        Retrying *everything* is deliberate: the Worker's handler is idempotent
        per action (`close_chat` and `reset_chat` are state transitions, and a
        redelivered `answer` costs one duplicate message at worst), so a retry
        is cheap while a lost callback is an answer the user is actively
        waiting on.
        """
        raw = json.dumps(payload).encode()
        last_error: Exception | None = None

        for attempt in range(1, self._retries + 1):
            try:
                response = await self._http.post(
                    self._callback_url,
                    content=raw,
                    headers={
                        "content-type": "application/json",
                        SIGNATURE_HEADER: sign_payload(self._secret, raw),
                    },
                )
                if 200 <= response.status_code < 300:
                    return response.json()
                # 4xx means the Worker understood and rejected — retrying the
                # same bytes cannot help, surface it immediately.
                response.raise_for_status()
            except (httpx.HTTPStatusError, httpx.TransportError) as err:
                last_error = err
                logger.warning(
                    "worker callback attempt %d/%d failed: %s", attempt, self._retries, err
                )

        raise WorkerError(
            f"callback to worker failed after {self._retries} attempts"
        ) from last_error

    # --- Typed wrappers over the five actions the Worker understands ---

    async def send_answer(
        self, chat_id: int, thread_id: int, text: str, parse_mode: str | None = "html"
    ) -> dict:
        payload: dict = {
            "action": "answer",
            "chat_id": chat_id,
            "thread_id": thread_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return await self.call(payload)

    async def send_typing(self, chat_id: int, thread_id: int) -> dict:
        return await self.call({"action": "typing", "chat_id": chat_id, "thread_id": thread_id})

    async def create_ticket(self, chat_id: int, subject: str, digest: str = "") -> dict:
        return await self.call(
            {"action": "create_ticket", "chat_id": chat_id, "subject": subject, "digest": digest}
        )

    async def close_chat(self, chat_id: int, thread_id: int, reason: str = "") -> dict:
        return await self.call(
            {"action": "close_chat", "chat_id": chat_id, "thread_id": thread_id, "reason": reason}
        )

        async def reset_chat(self, chat_id: int) -> dict:

            return await self.call({"action": "reset_chat", "chat_id": chat_id})

    # --- Read-only live data (resolved by the Worker from D1) ---

    async def get_packages(self) -> dict:
        """Fetch the current package catalog. Global — not user-scoped."""
        return await self.call({"action": "get_packages"})

    async def get_user_configs(self, chat_id: int) -> dict:
        """Fetch the calling user's purchased configs (ownership enforced server-side)."""
        return await self.call({"action": "get_user_configs", "chat_id": chat_id})

    # --- Telegram output (the agent never renders QR/config itself) ---

    async def send_qr(
        self,
        chat_id: int,
        text: str,
        t1: str = "",
        t2: str = "",
        theme: str | None = None,
        caption: str | None = None,
    ) -> dict:
        """Deliver a QR code image of `text` into the user's topic."""
        payload: dict = {"action": "send_qr", "chat_id": chat_id, "text": text, "t1": t1, "t2": t2}
        if theme:
            payload["theme"] = theme
        if caption:
            payload["caption"] = caption
        return await self.call(payload)

    async def send_config(self, chat_id: int, config_id: int) -> dict:
        """Deliver a purchased config (text + QR) to its owner."""
        return await self.call({"action": "send_config", "chat_id": chat_id, "config_id": config_id})

    # --- Progress UX: fire-and-forget, never retried (cosmetic only) ---

    async def send_draft(
        self,
        chat_id: int,
        text: str,
        draft_id: int,
        can_stop: bool = True,
        keep_on_stop: bool = True,
    ) -> bool:
        """Post a streaming draft to the user's topic.

        Single attempt, errors swallowed: a deleted/closed topic must not turn
        into a retry storm, and a draft is purely cosmetic — the final answer
        message is what actually delivers content.
        """
        return await self._best_effort(
            {
                "action": "draft",
                "chat_id": chat_id,
                "draft_id": draft_id,
                "text": text,
                "can_stop": can_stop,
                "keep_on_stop": keep_on_stop,
            }
        )

    async def send_stage(self, chat_id: int, step: str, draft_id: int) -> bool:
        """Signal a step change; the Worker picks a fun message for `step`."""
        return await self._best_effort(
            {"action": "stage", "chat_id": chat_id, "draft_id": draft_id, "step": step}
        )

    async def _post_signed(self, payload: dict) -> httpx.Response:
        """Signs and POSTs one payload, returning the raw response.

        Shared so `call` (retried, raises on 4xx) and the fire-and-forget
        draft/stage helpers sign the exact same bytes the Worker will verify.
        """
        raw = json.dumps(payload).encode()
        return await self._http.post(
            self._callback_url,
            content=raw,
            headers={
                "content-type": "application/json",
                SIGNATURE_HEADER: sign_payload(self._secret, raw),
            },
        )

    async def _best_effort(self, payload: dict) -> bool:
        """One POST, never raises — for cosmetic callbacks only."""
        try:
            await self._post_signed(payload)
            return True
        except Exception as err:  # noqa: BLE001 — dropping a draft is not fatal
            logger.debug("fire-and-forget callback dropped (%s): %s", payload.get("action"), err)
            return False
