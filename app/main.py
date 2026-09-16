from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI
from langchain_openrouter import ChatOpenRouter
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from app.agents.runner import AgentRunner
from app.core.config import get_settings
from app.web.fetch import Fetcher
from app.web.search import SearxngClient
from app.routers import chats, health
from app.worker import CallbackOutbox, WorkerClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Builds every long-lived connection once, tears them down on exit.

    The Postgres checkpointer is the conversation store: `setup()` creates the
    checkpoint tables on first boot and is a no-op after that, which is why
    the deployment needs no migration tool of its own.
    """
    settings = get_settings()

    http = httpx.AsyncClient(timeout=30)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        open=False,
        kwargs={"autocommit": True},
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()

    model = ChatOpenRouter(
        model=settings.openrouter_model,
        temperature=0.3,
        max_retries=2,
        app_title="NarnixVPN Assistant",
    )
    worker = WorkerClient(
        http,
        settings.worker_callback_url,
        settings.callback_secret,
        retries=settings.callback_retries,
    )
    outbox = CallbackOutbox(redis, worker)
    await outbox.start()

    # Shared, connection-pool-backed clients for the search/fetch tools.
    search = SearxngClient(http, settings).with_cache(redis)
    fetcher = Fetcher(http, settings).with_cache(redis)

    app.state.runner = AgentRunner(
        model, checkpointer, worker, outbox, search=search, fetcher=fetcher
    )
    app.state.redis = redis

    yield

    await app.state.runner.wait_for_pending()
    await outbox.stop()
    await pool.close()
    await redis.aclose()
    await http.aclose()


def create_app() -> FastAPI:
    application = FastAPI(
        title="Narnix AI Assistant",
        description=(
            "LangChain support agents behind the NarnixVPN Telegram bot. "
            "The Worker forwards user messages here and receives answers "
            "back through signed callbacks — nothing in this service talks "
            "to Telegram directly."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health.router)
    application.include_router(chats.router)
    return application


app = create_app()
