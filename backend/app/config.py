"""Runtime configuration (PRD Section 13). Values come from environment variables or a `.env` file."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

MB = 1024 * 1024


class Settings(BaseSettings):
    # `.env` is looked up in the working directory first, then the repo root (when run from backend/).
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    typesafe_api_key: SecretStr = SecretStr("")
    typesafe_base_url: str = "https://api.typesafe.ai"
    jev_model: str = "jev-latest"
    anthropic_api_key: SecretStr = SecretStr("")
    haiku_model: str = "claude-haiku-4-5-20251001"
    max_file_size_mb: int = 10
    max_files_per_batch: int = 20
    max_pdf_pages: int = 20
    classification_text_cap: int = 20000
    batch_ttl_minutes: int = 15
    max_concurrent_batches: int = 5
    allowed_origins: str = "http://localhost:5173"
    tesseract_cmd: str = "tesseract"
    log_level: str = "INFO"

    @property
    def jev_configured(self) -> bool:
        return bool(self.typesafe_api_key.get_secret_value().strip())

    @property
    def haiku_configured(self) -> bool:
        return bool(self.anthropic_api_key.get_secret_value().strip())

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * MB

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
