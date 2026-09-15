from langchain.tools import tool

from app.agents.tools import ToolContext


def create_ticket_tool(ctx: ToolContext):
    """Escalation: hands the conversation to a human via the ticket system."""

    @tool
    async def create_ticket(subject: str, digest: str = "") -> dict:
        """Open a support ticket so a human agent continues this conversation.

        Use this when the user explicitly asks to talk to a person, or when
        their question is about the NarnixVPN service but the FAQ does not
        cover it (account-specific problems, payment disputes, technical
        failures you cannot diagnose).

        Args:
            subject: One short line describing the problem, as you would
                summarise it to the support team. This becomes the ticket
                title the human sees first.
            digest: A brief recap of the conversation so far — what the user
                asked, what you tried, what remains unresolved. The support
                team reads this instead of the full chat.
        """
        return await ctx.worker.create_ticket(chat_id=ctx.chat_id, subject=subject, digest=digest)

    return create_ticket
