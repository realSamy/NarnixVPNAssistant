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

    @property
    def callback_secret(self) -> str:
        return self.ai_callback_secret.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor; FastAPI dependencies resolve through this."""
    return Settings()
