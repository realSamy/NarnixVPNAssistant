from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration.

    Field names map 1:1 to the environment variables (case-insensitive), and
    the names are chosen to mirror the Worker side (`AI_CALLBACK_SECRET` in
    particular is the *same* variable name in both projects) so the two halves
    of the deployment are configured in one vocabulary.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- OpenRouter ---
    openrouter_api_key: SecretStr
    openrouter_model: str = "google/gemini-2.5-flash"

    # --- Worker integration ---
    ai_callback_secret: SecretStr
    worker_callback_url: str

    # --- Infrastructure ---
    database_url: str = "postgresql://narnix:narnix@postgres:5432/narnix_ai"
    redis_url: str = "redis://redis:6379/0"

            # --- Behaviour ---
    rate_limit_messages: int = 20
    rate_limit_window_seconds: int = 300

    # Outbound callback retry policy (per delivery attempt, exponential backoff).
    callback_retries: int = 3

    # --- Web tools (live data + search) ---
    # Local SearXNG instance — no upstream API key, no quota. Optional; tools
    # simply report "unavailable" when empty/unreachable.
    searxng_url: str = ""
    search_results: int = 5
    # Shared cache TTL for search results and fetched pages (seconds).
    web_cache_ttl_seconds: int = 604800  # 7 days
    # Maximum length of a fetched page's extracted text returned to the agent.
    fetch_max_chars: int = 4000
    fetch_timeout_seconds: float = 15.0
    # Domains the agent is allowed to fetch. Keeps web access scoped to
    # NarnixVPN and its official client documentation — no arbitrary URLs.
    fetch_allowed_domains: list[str] = [
        "narnix.com",
        "docs.narnix.com",
        "github.com",     # client wikis (v2rayNG, v2box, streisand)
        "hiddify.com",
        "v2box.com",
    ]

    # --- Progress UI ---
    # Minimum time (ms) between SendMessageDraft callbacks to stay under
    # Telegram's 20-per-5-seconds / 40-per-30-seconds draft rate limit.
    draft_min_interval_ms: int = 550

    @property
    def callback_secret(self) -> str:
        return self.ai_callback_secret.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor; FastAPI dependencies resolve through this."""
    return Settings()
