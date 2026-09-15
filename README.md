# Narnix AI Assistant

The AI side of NarnixVPN's "Ask AI" feature: FastAPI services running LangChain
support agents for the [NarnixVPN Telegram bot](https://github.com/realSamy/NarnixVPN).
The bot (a Cloudflare Worker) never talks to Telegram's AI users directly and
this service never talks to Telegram at all — the two meet over signed HTTP
callbacks.

## How it works

```
Telegram ──webhook──▶ Cloudflare Worker ──POST (HMAC)──▶ this service
                          ▲                                  │
                          └────────POST (HMAC)───────────────┘
                            answer / typing / create_ticket /
                            close_chat / reset_chat
```

1. The Worker opens a temporary forum topic in the user's private chat and
   forwards each message to `POST /api/v1/chats/{session_id}/messages`.
2. This service answers `202` immediately and runs the agent in the
   background. Conversation history lives in Postgres (LangGraph Postgres
   checkpointer, keyed by `session_id`); Redis provides rate limiting,
   deduplication and a durable retry queue for callbacks.
3. When the agent finishes — optionally having called tools like
   `create_ticket` — the result is POSTed back to the Worker, which owns all
   user-facing rendering.

Every request in both directions is HMAC-SHA256 signed
(`X-Narnix-Signature: t=<unix>,v1=<hex>`) with a shared secret and a ±5-minute
replay window.

## Project layout

```
app/
  main.py            app factory + lifespan (all connections built here)
  core/              settings (pydantic-settings), HMAC signing
  routers/           inbound API: /api/v1/chats, health
  agents/            the agent: model, tools, prompts, FAQ, markdown→HTML
  worker/            signed HTTP client to the Worker + retry outbox
  schemas/           pydantic models for the Worker protocol
tests/               pytest: HMAC, rendering, API flow
```

## Development

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is fetched automatically.

```bash
uv sync                        # creates .venv from uv.lock
uv run fastapi dev             # http://127.0.0.1:8000/docs
uv run pytest
```

Configuration comes from the environment (`.env`, see `.env.example`).
`AI_CALLBACK_SECRET` must match the Worker's secret of the same name, and
`WORKER_CALLBACK_URL` must point at the Worker's `/ai/callback` endpoint.

## Deployment

```bash
cp .env.example .env           # fill in real values
docker compose up -d --build
```

Compose starts the API plus Postgres and Redis with healthchecks and a named
volume for data. The checkpointer's tables are created on first boot — no
separate migration step.

For a public deployment, put the API behind a reverse proxy with TLS (the
Worker calls it over HTTPS) and keep `/docs` disabled or protected.

## Adding agent capabilities

New agent abilities are new tool modules in `app/agents/tools/` added to
`build_tools`, plus one matching action branch on the Worker side
(`src/modules/assistant/callback.ts`). Nothing else changes — see
`create_ticket.py` for the pattern.
