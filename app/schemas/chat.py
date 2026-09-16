from pydantic import BaseModel, Field


class ChatUser(BaseModel):
    """The Telegram-side identity, carried through so the agent can greet and
    address the user without the Worker storing personal data anywhere else."""

    id: int
    first_name: str = ""
    lang: str = "fa"


class MessageIn(BaseModel):
    """One inbound user message, forwarded by the Worker's assistant relay.

    The Worker does not send conversation history — the Postgres checkpointer
    owns it, addressed by the URL's `session_id`. What rides along is the
    context the agent cannot know otherwise: who is talking and how close the
    conversation is to its message budget.
    """

    chat_id: int
    thread_id: int
    user: ChatUser
    text: str = Field(min_length=1, max_length=4000)
    """Count of user messages *including* this one."""
    message_count: int = Field(ge=1)
    """Soft budget the agent is prompted to wrap up against."""
    message_limit: int = Field(default=20, ge=1)
