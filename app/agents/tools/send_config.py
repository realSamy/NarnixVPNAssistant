"""``send_config`` — deliver a user's purchased v2ray config (and its QR).

Security is enforced on the Worker: it re-checks that the config belongs to
this chat in D1 before sending anything, so an agent can never hand another
user's config (or UUID/email) to someone else.
"""

from langchain.tools import tool


def send_config_tool(ctx):
    """Build the config-delivery tool bound to this conversation."""

    @tool
    async def send_config(config_id: int) -> str:
        """Send a purchased server config to this user as text + QR.

        The Worker verifies ownership in D1 (the config must belong to this
        chat) before sending anything, so an agent can never leak another
        user's config. The config goes to this user's private topic only.
        Pass the numeric id from ``get_user_configs``.

        Args:
            config_id: The id of the purchased config to deliver.
        """
        result = await ctx.worker.send_config(chat_id=ctx.chat_id, config_id=config_id)
        if result.get("ok"):
            return "Config sent to you ✅"
        return f"Could not send config {config_id} to this user."

    return send_config