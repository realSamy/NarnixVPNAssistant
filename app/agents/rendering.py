import html
import re

_FENCED_CODE = re.compile(r"```[^\n`]*\n?(.*?)```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_LIST_ITEM = re.compile(r"^[ \t]*[-*][ \t]+", re.MULTILINE)


def markdown_to_telegram_html(text: str) -> str:
    """Converts the model's markdown to the HTML subset Telegram parses.

    Models emit markdown no matter what the system prompt asks for, and
    Telegram's `parse_mode=HTML` is far more forgiving than `MarkdownV2` —
    so the conversion happens here, at the boundary, once. The Worker stays a
    dumb relay: it forwards `text` with `parse_mode: "html"` and never has to
    know what markdown is.

    Fenced and inline code are lifted out before everything else (code must be
    *escaped*, not formatted), the remainder is HTML-escaped and then given the
    few inline forms users actually read: bold, italic, links, headings, list
    bullets. Anything the model invents beyond that renders as literal text,
    which is ugly but never breaks the message.
    """
    code_blocks: list[str] = []

    def stash_block(match: re.Match) -> str:
        code_blocks.append(match.group(1).strip("\n"))
        return f"\x00BLOCK{len(code_blocks) - 1}\x00"

    text = _FENCED_CODE.sub(stash_block, text)

    inline_code: list[str] = []

    def stash_inline(match: re.Match) -> str:
        inline_code.append(match.group(1))
        return f"\x00INLINE{len(inline_code) - 1}\x00"

    text = _INLINE_CODE.sub(stash_inline, text)

    escaped = html.escape(text)
    escaped = _BOLD.sub(r"<b>\1</b>", escaped)
    escaped = _ITALIC.sub(r"<i>\1</i>", escaped)
    escaped = _LINK.sub(r'<a href="\2">\1</a>', escaped)
    escaped = _HEADING.sub(r"<b>\1</b>", escaped)
    escaped = _LIST_ITEM.sub("•  ", escaped)

    escaped = re.sub(
        r"\x00BLOCK(\d+)\x00",
        lambda m: f"<pre>{html.escape(code_blocks[int(m.group(1))])}</pre>",
        escaped,
    )
    escaped = re.sub(
        r"\x00INLINE(\d+)\x00",
        lambda m: f"<code>{html.escape(inline_code[int(m.group(1))])}</code>",
        escaped,
    )

    return escaped
