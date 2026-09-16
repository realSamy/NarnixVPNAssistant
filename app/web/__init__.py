"""HTTP-backed tools that reach the outside world on the agent's behalf.

Everything external — web search and page fetching — lives behind a Redis cache
so the agent calls them liberally while the cost to upstreams stays bounded.
A failed external call returns a structured ``"unavailable"`` result rather
than raising, so a down search instance never breaks a turn; the agent simply
answers from the FAQ and live data, and can escalate with ``create_ticket``.
"""