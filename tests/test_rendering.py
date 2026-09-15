from app.agents.rendering import markdown_to_telegram_html


def test_bold():
    assert markdown_to_telegram_html("**hi** there") == "<b>hi</b> there"


def test_escapes_html_outside_code():
    assert markdown_to_telegram_html("a < b & c") == "a &lt; b &amp; c"


def test_inline_code_is_escaped_not_formatted():
    assert markdown_to_telegram_html("use `x < y`") == "use <code>x &lt; y</code>"


def test_fenced_code_becomes_pre():
    out = markdown_to_telegram_html("before\n```\n<b>raw</b>\n```\nafter")
    assert "<pre>&lt;b&gt;raw&lt;/b&gt;</pre>" in out


def test_link():
    assert (
        markdown_to_telegram_html("[docs](https://example.com)")
        == '<a href="https://example.com">docs</a>'
    )


def test_heading_and_list_items():
    out = markdown_to_telegram_html("## Steps\n- first\n- second")
    assert "<b>Steps</b>" in out
    assert "•  first" in out
