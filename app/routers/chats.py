import logging

from fastapi import APIRouter, HTTPException, Request

from app.core.config import get_settings
from app.core.security import SIGNATURE_HEADER, verify_payload
from app.schemas.chat import MessageIn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chats", tags=["chats"])

# How long an accepted message stays "already processed". Generous on purpose:
# it is the deduplication window for Telegram redelivering an update, not a
# rate limiter — the rate limiter below is that.
DEDUP_TTL_SECONDS = 3600


@router.post("/{session_id}/messages", status_code=202)
async def receive_message(session_id: str, request: Request) -> dict:
    """Accepts one user message from the Worker and returns immediately.

    This endpoint is the Worker's only way in, and three things happen before
    the payload is trusted or acted on:

    1. **Signature** — HMAC over the *raw* body, so serialization can never
       make the Worker sign different bytes than the backend verifies.
    2. **Rate limit** — per-user, Redis sliding window; a 429 here is relayed
       to the user verbatim by the Worker's relay.
    3. **Deduplication** — Telegram may redeliver an update; a SET-NX lock on
       `(session, chat, count)` turns the redelivery into a no-op instead of a
       second agent run.

    The agent run itself is scheduled and *not* awaited: the whole point of
    the bidirectional protocol is that the Worker's webhook does not wait on
    the model. The answer arrives later on the Worker's `/ai/callback`.
    """
    settings = get_settings()
    raw = await request.body()

    if not verify_payload(settings.callback_secret, raw, request.headers.get(SIGNATURE_HEADER)):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        message = MessageIn.model_validate_json(raw)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=f"invalid payload: {err}") from err

    redis = request.app.state.redis

    rate_key = f"narnix:rl:{message.user.id}"
    count = await redis.incr(rate_key)
    if count == 1:
        await redis.expire(rate_key, settings.rate_limit_window_seconds)
    if count > settings.rate_limit_messages:
        return {"status": "rate_limited"}

    dedup_key = f"narnix:msg:{session_id}:{message.chat_id}:{message.message_count}"
    if not await redis.set(dedup_key, "1", nx=True, ex=DEDUP_TTL_SECONDS):
        logger.info("duplicate message ignored (chat %s, count %s)", message.chat_id, message.message_count)
        return {"status": "accepted", "duplicate": True}

    logger.info(
        "message accepted (session %s, chat %s, %d/%d used)",
        session_id, message.chat_id, message.message_count, message.message_limit,
    )
    request.app.state.runner.schedule(session_id, message)
    return {"status": "accepted"}
