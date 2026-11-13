"""Configuración de la aplicación (pydantic-settings, leída de `.env`)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_DB = "postgresql+asyncpg://quant_admin:quant_secret_dev@localhost:5432"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = f"{_DEV_DB}/quant_terminal_db"
    test_database_url: str = f"{_DEV_DB}/quant_terminal_test"
    db_connect_timeout_s: float = 3.0

    # OANDA (practice por defecto). El token nunca se muestra en repr/logs.
    oanda_api_token: SecretStr | None = None
    oanda_account_id: str | None = None
    oanda_base_url: str = "https://api-fxpractice.oanda.com"

    # Horizontes de backfill por defecto (D17). Binance y demás proveedores.
    backfill_days_5m: int = 90
    backfill_days_15m: int = 365
    backfill_years_1h: int = 5
    backfill_years_4h: int = 5
    backfill_years_1d: int = 5

    # Horizontes de Yahoo (D30): límites del proveedor, verificados el 2026-11-13.
    backfill_days_5m_yahoo: int = 59
    backfill_days_15m_yahoo: int = 59
    backfill_days_1h_yahoo: int = 729
    backfill_days_4h_yahoo: int = 729


@lru_cache
def get_settings() -> Settings:
    return Settings()
