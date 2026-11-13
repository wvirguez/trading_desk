"""Configuración de la aplicación (pydantic-settings, leída de `.env`)."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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

    # Riesgo y motor cuantitativo (Fase 2, D51-D69). Porcentajes en unidades de % (1.0 = 1 %).
    risk_per_trade_pct: Decimal = Field(default=Decimal("1.0"), gt=0, le=5)
    max_daily_loss_pct: Decimal = Field(default=Decimal("3.0"), gt=0, le=20)
    min_rr: Decimal = Field(default=Decimal("1.8"), ge=1, le=20)
    kelly_fraction: Decimal = Field(default=Decimal("0.25"), gt=0, le=1)
    max_open_risk_pct: Decimal = Field(default=Decimal("3.0"), gt=0, le=50)
    max_correlated_risk_pct: Decimal = Field(default=Decimal("2.0"), gt=0, le=50)
    correlation_window: int = Field(default=100, ge=20, le=5000)
    correlation_threshold: Decimal = Field(default=Decimal("0.7"), gt=0, le=1)
    backtest_max_bars: int = Field(default=50000, ge=100, le=1_000_000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
