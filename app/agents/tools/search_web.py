"""``search_web`` — live web search via the self-hosted SearXNG instance.

SearXNG is private, self-hostable, and keyless. Queries are cached in Redis so
the second user asking the same thing is instant. The system prompt tells the
agent to search in English and answer in the user's language — the tool
itself is language-agnostic.
"""

from langchain.tools import tool


def search_web_tool(ctx):
    """Build the search tool bound to this conversation's search client."""

    @tool
    async def search_web(query: str) -> str:
        """Search the web for up-to-date answers about NarnixVPN or V2Ray clients.

        Use this when the FAQ does not cover the question and the answer may
        exist on the public web — e.g. how to import a config into a specific
        client app, or whether a given client works with NarnixVPN. Searches
        are always performed in English and cached. Do not use this for
        anything unrelated to NarnixVPN.

        Args:
            query: The search terms, in English. Be specific — include the
                client name and the action ("how to import subscription into
                Hiddify iOS").
        """
        results = await ctx.search.search(query)
        lines = ["Results:"]
        for r in results:
            if r.url:
                lines.append(f"- {r.title} ({r.url}): {r.content}")
            else:
                lines.append(f"- {r.content}")
        return "\n".join(lines)

    return search_web