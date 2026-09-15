from langchain.tools import tool

from app.agents.tools import ToolContext


def close_chat_tool(ctx: ToolContext):
    """Ends the conversation and removes the temporary topic."""

    @tool
    async def close_chat(reason: str = "") -> dict:
        """Close this AI chat and delete its temporary topic.

        Only use this when the user no longer needs the conversation's
        content: their questions are answered, nothing is pending, and they
        said goodbye or moved on. If they may still want to scroll back to an
        answer, do NOT close — losing the topic loses that information. When
        in doubt, keep it open; the user has a close button of their own.

        Must be preceded by create_ticket if you are closing because the user
        still needs human help — closing alone strands them.

        Args:
            reason: One short line for the ops log, not shown to the user.
        """
        return await ctx.worker.close_chat(
            chat_id=ctx.chat_id, thread_id=ctx.thread_id, reason=reason
        )

    return close_chat
