"""Configuración de la aplicación (pydantic-settings, leída de `.env`)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_DB = "postgresql+asyncpg://quant_admin:quant_secret_dev@localhost:5432"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = f"{_DEV_DB}/quant_terminal_db"
    test_database_url: str = f"{_DEV_DB}/quant_terminal_test"
    db_connect_timeout_s: float = 3.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
