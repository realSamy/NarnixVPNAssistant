import asyncio
import json
import logging

import redis.asyncio as aioredis

from app.worker.client import WorkerClient

logger = logging.getLogger(__name__)

OUTBOX_KEY = "narnix:callback-outbox"

# A queued callback is retried on this cadence until it delivers. Twenty
# rounds (~2 minutes of worker unavailability over ~16 minutes of drain
# intervals) is far beyond any realistic deploy or restart window; past that,
# the failure is logged loudly and dropped — the user can resend, and a
# message still sitting in their AI topic is the visible cue.
DRAIN_INTERVAL_SECONDS = 5
MAX_ROUNDS = 20


class CallbackOutbox:
    """Redis-backed retry queue for worker callbacks that could not deliver.

    The agent runs inside an `asyncio` task; if the process dies mid-run, a
    plain in-memory retry dies with it. This outbox survives: the failed
    callback is pushed to a Redis list, and a drain task re-delivers until the
    worker accepts. That is the difference between "the user re-sends" and
    "the user's question vanished".
    """

    def __init__(self, redis: aioredis.Redis, worker: WorkerClient):
        self._redis = redis
        self._worker = worker
        self._drain_task: asyncio.Task | None = None

    async def enqueue(self, payload: dict) -> None:
        """Queues a failed callback for later delivery."""
        await self._redis.rpush(OUTBOX_KEY, json.dumps({"rounds": 0, "payload": payload}))
        logger.warning("callback queued for retry: %s", payload.get("action"))

    async def start(self) -> None:
        self._drain_task = asyncio.create_task(self._drain_loop(), name="callback-outbox-drain")

    async def stop(self) -> None:
        if self._drain_task:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass

    async def _drain_loop(self) -> None:
        while True:
            try:
                await self._drain_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("outbox drain round failed")
            await asyncio.sleep(DRAIN_INTERVAL_SECONDS)

    async def _drain_once(self) -> None:
        """Delivers everything currently queued; failed items requeue with a
        bumped round count, preserving their order."""
        while True:
            raw = await self._redis.lindex(OUTBOX_KEY, 0)
            if raw is None:
                return

            entry = json.loads(raw)
            try:
                await self._worker.call(entry["payload"])
                await self._redis.lpop(OUTBOX_KEY)
            except Exception:
                entry["rounds"] += 1
                if entry["rounds"] >= MAX_ROUNDS:
                    logger.error(
                        "dropping callback after %d rounds: %s",
                        entry["rounds"],
                        entry["payload"].get("action"),
                    )
                    await self._redis.lpop(OUTBOX_KEY)
                else:
                    # Rotate to the back so one poisoned entry cannot starve
                    # the rest of the queue.
                    await self._redis.lpop(OUTBOX_KEY)
                    await self._redis.rpush(OUTBOX_KEY, json.dumps(entry))
                return
