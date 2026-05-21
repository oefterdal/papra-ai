import os
from typing import Any, cast

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    papra_base_url: str = "http://papra:1221"
    papra_api_token: str
    papra_webhook_secret: str
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "minicpm-v:8b"
    pdf_max_pages: int = Field(default=10, ge=1)
    pdf_render_dpi: int = Field(default=150, ge=72, le=300)
    log_level: str = Field(
        default="INFO",
        pattern=r"^(CRITICAL|ERROR|WARNING|INFO|DEBUG)$",
    )
    papra_ai_tag_color: str = Field(
        default="#5B8DEF",
        pattern=r"^#[0-9A-Fa-f]{6}$",
    )


def get_settings() -> Settings:
    env_file = cast(Any, {"_env_file": os.getenv("PAPRA_AI_ENV_FILE", ".env")})
    return Settings(**env_file)
