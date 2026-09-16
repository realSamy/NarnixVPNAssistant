"""``fetch_page`` — read an allowlisted URL so the agent has full context.

Restricted to NarnixVPN and official client-docs domains (enforced in the
fetcher itself). The agent may only ever hand this tool a URL it obtained
from ``search_web`` — never an arbitrary link from the user.
"""

from langchain.tools import tool


def fetch_page_tool(ctx):
    """Build the page-fetch tool bound to this conversation's fetcher."""

    @tool
    async def fetch_page(url: str) -> str:
        """Fetch and return the readable text of a documentation page.

        Use this to read the full instructions on a page returned by
        ``search_web`` when the snippet was not enough. Only URLs from
        NarnixVPN and official client-doc sites (github.com, hiddify.com,
        v2box.com, docs.narnix.com) are allowed — arbitrary links are refused.

        The returned text is capped to a few thousand characters; if the page
        is large, read the part you need and request it again for more.

        Args:
            url: The exact URL from a search result.
        """
        result = await ctx.fetcher.fetch(url)
        return result.text

    return fetch_page