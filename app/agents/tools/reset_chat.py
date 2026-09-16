from langchain.tools import tool

from app.agents.tools import ToolContext


def reset_chat_tool(ctx: ToolContext):
    """Starts the conversation over inside the same topic."""

    @tool
    async def reset_chat(reason: str = "") -> dict:
        """Reset the conversation: the topic stays, the history is wiped.

        Use this when the message budget is nearly spent, the user's issue is
        resolved, and nothing of value would be lost by starting fresh. Give
        your final answer first, then call this. If the issue is NOT resolved,
        escalate with create_ticket instead — resetting a live problem just
        makes the user repeat themselves.

        Args:
            reason: One short line for the ops log, not shown to the user.
        """
        return await ctx.worker.reset_chat(chat_id=ctx.chat_id, reason=reason)

    return reset_chat
