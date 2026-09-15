"""The tools the support agent can call, all backed by signed Worker callbacks.

Tools are built per run from a ``ToolContext`` because they carry the identity
of the conversation they act on — a module-level singleton tool would need
that threaded through every call, which LangChain's tool schema cannot
express. Building three closures per request costs microseconds against a
model call measured in seconds.

Adding a capability later (e.g. AI-driven orders) means one module here with
one factory, added to ``build_tools`` — the Worker side gains an action branch
and nothing else changes.
"""

from dataclasses import dataclass

from app.worker.client import WorkerClient


@dataclass(frozen=True)
class ToolContext:
    """The conversation a tool acts on. Frozen so tools cannot drift."""

    worker: WorkerClient
    chat_id: int
    thread_id: int


def build_tools(ctx: ToolContext) -> list:
    from app.agents.tools.close_chat import close_chat_tool
    from app.agents.tools.create_ticket import create_ticket_tool
    from app.agents.tools.reset_chat import reset_chat_tool

    return [create_ticket_tool(ctx), close_chat_tool(ctx), reset_chat_tool(ctx)]
