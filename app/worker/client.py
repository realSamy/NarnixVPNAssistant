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
