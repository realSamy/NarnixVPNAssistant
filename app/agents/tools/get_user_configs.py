"""``get_user_configs`` — the user's purchased v2ray configs (live, owned).

Read-only: it lists the user's own subscription configs (id, package, panel,
quota, expiry, best-effort live usage, and the subscription URL), but never
exposes secrets — the per-config v2ray UUID, email, and panel api_key stay in
D1. The agent passes a returned ``config_id`` to ``send_config`` to hand the
user their actual config; it never sees the secret material itself.
"""

import json

from langchain.tools import tool


def get_user_configs_tool(ctx):
    """Build the user-configs tool bound to this conversation."""

    @tool
    async def get_user_configs() -> str:
        """List the calling user's active v2ray configs and subscription link.

        Returns a JSON list, one entry per config with: id, package title,
        panel name, data quota (GB), expires_at, created_at, best-effort
        used_gb (read live from the panel; may be "unavailable" if the panel
        is down), and the subscription URL the user can import. This is the
        user's OWN configs — pass an entry's id to send_config to deliver it.
        Never reveal another user's configs; the worker enforces ownership.
        """
        result = await ctx.worker.get_user_configs(chat_id=ctx.chat_id)
        return json.dumps(result, ensure_ascii=False)

    return get_user_configs