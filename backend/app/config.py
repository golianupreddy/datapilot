from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str
    llm_model: str = "gemini-2.5-flash"
    embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768
    llm_thinking_budget: int = 0
    llm_max_retries: int = 5
    llm_min_interval_seconds: float = 0.0
    llm_models: str = ""
    llm_call_deadline_s: float = 30.0
    llm_request_timeout_s: float = 20.0
    llm_retries_per_model: int = 1
    llm_cooldown_s: float = 60.0

    database_url_admin: str
    database_url_ro: str

    max_rows: int = 500
    statement_timeout_ms: int = 8000
    max_sql_retries: int = 3
    retrieval_top_k: int = 4
    cache_ttl_seconds: int = 600
    rate_limit_per_minute: int = 12

    cors_origins: str = "http://localhost:5173"
    cors_origin_regex: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
