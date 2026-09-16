import asyncio
import logging

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openrouter import ChatOpenRouter
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agents.prompts.support import build_system_prompt
from app.agents.rendering import markdown_to_telegram_html
from app.agents.tools import ToolContext, build_tools
from app.schemas.chat import MessageIn
from app.worker.client import WorkerClient
from app.worker.outbox import CallbackOutbox

logger = logging.getLogger(__name__)


def _final_text(messages: list[BaseMessage]) -> str:
    """The agent's last AI message, flattened to a string.

    AIMessage.content may be a plain string or a list of content blocks
    depending on the model; the text is what matters here.
    """
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            content = message.content
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                return "".join(
                    block.get("text", "") for block in content if isinstance(block, dict)
                ).strip()
    return ""


class AgentRunner:
    """Owns the agent loop and its delivery guarantees.

    One runner lives for the process lifetime (`app.state.runner`); a turn is
    one `_run_turn` invocation, spawned per inbound message and tracked so a
    shutdown can wait on in-flight work rather than sever it.

    The agent is constructed per turn on purpose: its system prompt embeds
    per-conversation state (language, message budget) and per-turn tool
    closures, and graph construction is microseconds against a model call.
    """

    def __init__(
        self,
        model: ChatOpenRouter,
        checkpointer: BaseCheckpointSaver,
        worker: WorkerClient,
        outbox: CallbackOutbox,
    ):
        self._model = model
        self._checkpointer = checkpointer
        self._worker = worker
        self._outbox = outbox
        self._tasks: set[asyncio.Task] = set()

    def schedule(self, session_id: str, message: MessageIn) -> asyncio.Task:
        """Runs a turn in the background; the HTTP response has already left."""
        task = asyncio.create_task(self._run_turn(session_id, message))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def wait_for_pending(self) -> None:
        """Graceful-shutdown hook: let in-flight turns finish delivering."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_turn(self, session_id: str, message: MessageIn) -> None:
        try:
            await self._run_turn_inner(session_id, message)
        except Exception:
            logger.exception("agent turn failed (session %s, chat %s)", session_id, message.chat_id)
            await self._deliver_answer(
                message,
                "Sorry — something went wrong while thinking. Please try again in a moment."
                if message.user.lang != "fa"
                else "متاسفانه در پردازش پیامت مشکلی پیش آمد. لطفاً چند لحظه بعد دوباره امتحان کن.",
                parse_mode=None,
            )

    async def _run_turn_inner(self, session_id: str, message: MessageIn) -> None:
        tools = build_tools(ToolContext(worker=self._worker, chat_id=message.chat_id, thread_id=message.thread_id))
        agent = create_agent(
            model=self._model,
            tools=tools,
            system_prompt=build_system_prompt(message.user, message.message_count, message.message_limit),
            checkpointer=self._checkpointer,
        )

        # The typing indicator from the relay dies after ~5s; long tool-using
        # turns re-trigger it once here. Cosmetic, so failure is ignorable.
        try:
            await self._worker.send_typing(message.chat_id, message.thread_id)
        except Exception:
            pass

        result = await agent.ainvoke(
            {"messages": [("user", message.text)]},
            config=RunnableConfig(configurable={"thread_id": session_id}),
        )

        reply = _final_text(result["messages"])
        if not reply:
            logger.warning("agent produced no text (session %s)", session_id)
            return

        await self._deliver_answer(message, markdown_to_telegram_html(reply), parse_mode="html")

    async def _deliver_answer(self, message: MessageIn, text: str, parse_mode: str | None) -> None:
        payload: dict = {
            "action": "answer",
            "chat_id": message.chat_id,
            "thread_id": message.thread_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            await self._worker.call(payload)
        except Exception:
            # The turn succeeded; only the delivery failed. Queue it — the
            # outbox retries until the worker is reachable again.
            logger.exception("answer delivery failed, queueing (chat %s)", message.chat_id)
            await self._outbox.enqueue(payload)
