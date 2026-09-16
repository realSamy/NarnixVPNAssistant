"""The tools the support agent can call, all backed by signed Worker callbacks.

Tools are built per run from a ``ToolContext`` because they carry the identity
of the conversation they act on — a module-level singleton tool would need
that threaded through every call, which LangChain's tool schema cannot
express. Building the closures per request costs microseconds against a model
call measured in seconds.

Capability map (and where each one executes):

- ``get_packages`` / ``get_user_configs``: read-only live data, resolved by the
  Worker from D1. The backend never sees the user's personal identifiers
  beyond the Telegram id it already has.
- ``send_qr`` / ``send_config``: Telegram output only. The Worker renders QR
  codes and delivers configs; ``send_config`` re-checks ownership in D1, so an
  agent can never leak another user's data.
- ``search_web`` / ``fetch_page``: pure-backend, hitting a self-hosted
  SearXNG + Redis cache. The agent can only fetch allowlisted domains.
- ``create_ticket`` / ``close_chat`` / ``reset_chat``: the original lifecycle
  tools, unchanged in spirit.

The progress UX (``send_stage`` / ``send_draft``) is driven by the runner
directly, not via a tool — it must not be something the agent decides to do.

Adding a capability later (e.g. AI-driven orders) means one module here with
one factory, registered in ``build_tools`` — and a new action branch on the
Worker. Nothing else changes.
"""

from dataclasses import dataclass

from app.web.fetch import Fetcher
from app.web.search import SearxngClient
from app.worker.client import WorkerClient


@dataclass(frozen=True)
class ToolContext:
    """The conversation a tool acts on. Frozen so tools cannot drift.

    ``user_id`` is the Telegram user id — kept for future order-issuing tools
    (today's tools route through ``chat_id``, which the Worker already ties to
    a verified owner). ``lang`` is the user's locale, for any locale-aware
    formatting a tool may eventually need.
    """

    worker: WorkerClient
    chat_id: int
    thread_id: int
    user_id: int
    lang: str
    search: SearxngClient
    fetcher: Fetcher


def build_tools(ctx: ToolContext) -> list:
    """Assemble the tool list for one run.

    Imports are done lazily inside the function so the agent's import graph
    never pays for a tool (and its optional deps) unless the agent actually
    gets past tool selection to build them — microseconds either way, but it
    keeps the cold-start path honest.
    """
    from app.agents.tools.close_chat import close_chat_tool
    from app.agents.tools.create_ticket import create_ticket_tool
    from app.agents.tools.fetch_page import fetch_page_tool
    from app.agents.tools.get_packages import get_packages_tool
    from app.agents.tools.get_user_configs import get_user_configs_tool
    from app.agents.tools.reset_chat import reset_chat_tool
    from app.agents.tools.search_web import search_web_tool
    from app.agents.tools.send_config import send_config_tool
    from app.agents.tools.send_qr import send_qr_tool

    return [
        get_packages_tool(ctx),
        get_user_configs_tool(ctx),
        send_qr_tool(ctx),
        send_config_tool(ctx),
        search_web_tool(ctx),
        fetch_page_tool(ctx),
        create_ticket_tool(ctx),
        close_chat_tool(ctx),
        reset_chat_tool(ctx),
    ]
