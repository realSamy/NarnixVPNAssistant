import asyncio
import logging
import time

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_openrouter import ChatOpenRouter
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agents.prompts.support import build_system_prompt
from app.agents.tools import ToolContext, build_tools
from app.core import config
from app.schemas.chat import MessageIn
from app.worker.client import WorkerClient
from app.worker.outbox import CallbackOutbox

logger = logging.getLogger(__name__)

# Tool name -> progress "step" the Worker renders as a fun status message on
# the user's draft. Unrecognised tools fall back to "thinking".
_STAGE_FOR_TOOL = {
    "search_web": "researching",
    "fetch_page": "researching",
    "get_packages": "checking",
    "get_user_configs": "checking",
    "send_qr": "preparing",
    "send_config": "preparing",
    "create_ticket": "escalating",
}


def _content_to_text(content) -> str:
    """Extract a plain string from content that may be a str or a list of
    content blocks (an AIMessage/AIMessageChunk can be either)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return ""


def _final_text(messages: list[BaseMessage]) -> str:
    """The agent's last AI message, flattened to a string.

    AIMessage.content may be a plain string or a list of content blocks
    depending on the model; the text is what matters here.
    """
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return _content_to_text(message.content)
    return ""


def _final_output_text(output) -> str:
    """Best-effort extraction of the final answer from an on_chain_end output.

    create_agent's runnable final output is {"messages": [...]}; the answer is
    the last AIMessage. Returns "" if the shape is unexpected, so the caller
    falls back to the accumulated buffer instead of shipping a wrong answer.
    """
    if isinstance(output, dict):
        if "messages" in output:
            return _final_text(list(output["messages"]))
        return ""
    if hasattr(output, "content"):
        return _content_to_text(output.content)
    return ""


class AgentRunner:
    """Owns the agent loop and its delivery guarantees.

    One runner lives for the process lifetime (app.state.runner); a turn is one
    _run_turn invocation, spawned per inbound message and tracked so a shutdown
    can wait on in-flight work rather than severing it.

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
        search,
        fetcher,
    ):
        self._model = model
        self._checkpointer = checkpointer
        self._worker = worker
        self._outbox = outbox
        self._search = search
        self._fetcher = fetcher
        self._tasks: set[asyncio.Task] = set()
        self._draft_seq = 0

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
            logger.exception(
                "agent turn failed (session %s, chat %s)", session_id, message.chat_id
            )
            await self._deliver_answer(
                message,
                "Sorry, something went wrong while thinking. Please try again shortly."
                if message.user.lang != "fa"
                else "متاسفانه در پردازش پیامت مشکلی پیش آمد. لطفاً چند لحظه بعد دوباره امتحان کن.",
                parse_mode=None,
            )

    async def _run_turn_inner(self, session_id: str, message: MessageIn) -> None:
        tool_ctx = ToolContext(
            worker=self._worker,
            chat_id=message.chat_id,
            thread_id=message.thread_id,
            user_id=message.user.id,
            lang=message.user.lang,
            search=self._search,
            fetcher=self._fetcher,
        )
        tools = build_tools(tool_ctx)
        agent = create_agent(
            model=self._model,
            tools=tools,
            system_prompt=build_system_prompt(
                message.user, message.message_count, message.message_limit
            ),
            checkpointer=self._checkpointer,
        )

        settings = config.get_settings()
        interval_ms = settings.draft_min_interval_ms
        draft_id = self._next_draft_id()
        chat_id = message.chat_id

        # Seed a draft so the user sees "thinking" immediately. The Worker holds
        # one live draft per (chat, thread, draft_id); later drafts replace it.
        thinking = "در حال فکر کردن…" if message.user.lang == "fa" else "Thinking…"
        await self._worker.send_draft(chat_id, thinking, draft_id)

        buffer = ""
        last_send = 0.0
        final_answer = ""

        async def flush() -> None:
            """Throttled live-update of the draft with the accumulated text."""
            nonlocal last_send
            if not buffer:
                return
            now = time.monotonic()
            if (now - last_send) * 1000 < interval_ms:
                return
            last_send = now
            await self._worker.send_draft(chat_id, buffer, draft_id)

        runnable_config = RunnableConfig(configurable={"thread_id": session_id})
        async for event in agent.astream_events(
            {"messages": [("user", message.text)]},
            config=runnable_config,
            version="v2",
        ):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = (event.get("data") or {}).get("chunk")
                text = _content_to_text(getattr(chunk, "content", None))
                if text:
                    buffer += text
                    await flush()
            elif kind == "on_tool_start":
                # A tool call ends the current generation; the answer resumes
                # after it returns, so reset the buffer so the final draft only
                # reflects the in-progress generation.
                buffer = ""
                name = event.get("name", "") or "tool"
                await self._worker.send_stage(
                    chat_id, _STAGE_FOR_TOOL.get(name, "thinking"), draft_id
                )
            elif kind == "on_chain_end":
                # The final output is the completed conversation; prefer its
                # last AIMessage over the accumulated buffer, which may contain
                # transitional text from before tool calls.
                out = (event.get("data") or {}).get("output")
                extracted = _final_output_text(out)
                if extracted:
                    final_answer = extracted

        reply = final_answer or buffer.strip()
        if not reply:
            logger.warning("agent produced no text (session %s)", session_id)
            return

        # Clear the in-progress draft (empty text) before posting the answer so
        # a stale partial draft can never shadow the real message.
        await self._worker.send_draft(chat_id, "", draft_id)
        await self._deliver_answer(
            message, reply, parse_mode="html"
        )

    def _next_draft_id(self) -> int:
        self._draft_seq += 1
        return self._draft_seq

    async def _deliver_answer(
        self, message: MessageIn, text: str, parse_mode: str | None
    ) -> None:
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
            # The turn succeeded; only the delivery failed. Queue it -- the
            # outbox retries until the worker is reachable again.
            logger.exception(
                "answer delivery failed, queueing (chat %s)", message.chat_id
            )
            await self._outbox.enqueue(payload)
