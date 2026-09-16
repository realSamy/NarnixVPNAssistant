"""``send_qr`` — deliver a QR code of a config or subscription URL, as an image."""

from langchain.tools import tool

# The Worker's renderer (DEFAULT_QR_SERVICE) recognises these; mirroring the
# set here lets the agent pick a theme without guessing.
_VALID_THEMES = {"common", "uncommon", "rare", "mythic", "legendary"}


def send_qr_tool(ctx):
    """Build the QR-sending tool bound to this conversation."""

    @tool
    async def send_qr(
        text: str,
        t1: str = "",
        t2: str = "",
        theme: str = "mythic",
        caption: str = "",
    ) -> str:
        """Send a scannable QR code of `text` as an image into this chat.

        Use this when the user wants a QR for a v2ray config or subscription
        URL instead of (or in addition to) plain text. The QR is rendered by
        the Worker's image service and sent directly to this user's topic.

        Args:
            text: The value to encode — a config URL or subscription link.
            t1: Short top label on the QR badge (e.g. "NarnixVPN").
            t2: Short bottom label on the QR badge (e.g. "Premium").
            theme: Visual theme — one of common, uncommon, rare, mythic,
                legendary. Defaults to mythic.
            caption: Optional text shown under the image.
        """
        result = await ctx.worker.send_qr(
            chat_id=ctx.chat_id,
            text=text,
            t1=t1,
            t2=t2,
            theme=theme if theme in _VALID_THEMES else None,
            caption=caption or None,
        )
        return "QR code sent 📸" if result.get("ok") else "QR code could not be sent."

    return send_qr