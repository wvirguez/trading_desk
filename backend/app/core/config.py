"""Configuración de la aplicación (pydantic-settings, leída de `.env`)."""

from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal, Self

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
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

    # Frontend / CORS / WebSocket (Fase 4)
    cors_allow_origins_raw: str = Field(
        default="http://localhost:3000",
        validation_alias="CORS_ALLOW_ORIGINS",
    )
    ws_poll_interval_s: float = Field(
        default=2.0,
        ge=0.5,
        le=60.0,
        validation_alias="WS_POLL_INTERVAL_S",
    )

    @field_validator("cors_allow_origins_raw", mode="before")
    @classmethod
    def _validate_cors_origins_raw(cls, value: Any) -> Any:
        """Valida CORS_ALLOW_ORIGINS antes de parsear."""
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("CORS_ALLOW_ORIGINS no puede ser una cadena vacía")
            origins = [o.strip() for o in value.split(",") if o.strip()]
            if "*" in origins:
                raise ValueError("CORS_ALLOW_ORIGINS no puede contener '*' (comodín)")
        return value

    @computed_field
    def cors_allow_origins(self) -> list[str]:
        """Lista de orígenes CORS parseada desde CORS_ALLOW_ORIGINS."""
        return [o.strip() for o in self.cors_allow_origins_raw.split(",") if o.strip()]

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

    # Agentes (Fase 3, D81-D97). La clave nunca se muestra en repr/logs; vacía = agentes
    # deshabilitados.
    agent_provider: Literal["anthropic", "google"] = "anthropic"
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    agent_model: str = Field(default="claude-sonnet-5-5", min_length=1)
    agent_auditor_model: str | None = None
    # Tope de la ejecución COMPLETA de un agente (`agent.run(timeout=...)`), no de cada llamada.
    agent_timeout_s: float = Field(default=120, gt=0, le=3600)
    agent_max_tokens_per_analysis: int = Field(default=60000, ge=1000, le=10_000_000)
    agent_max_cost_usd_per_analysis: Decimal | None = Field(default=None, gt=0)
    agent_price_input_usd_per_mtok: Decimal | None = Field(default=None, ge=0)
    agent_price_output_usd_per_mtok: Decimal | None = Field(default=None, ge=0)
    account_equity_usd: Decimal = Field(default=Decimal("10000"), gt=0)
    analysis_lookback_bars: int = Field(default=500, ge=100, le=5000)
    proposal_target_rr: Decimal = Field(default=Decimal("2.0"), ge=1, le=20)
    proposal_sl_atr_buffer: Decimal = Field(default=Decimal("0.5"), ge=0, le=10)

    @field_validator(
        "anthropic_api_key",
        "gemini_api_key",
        "agent_auditor_model",
        "agent_max_cost_usd_per_analysis",
        "agent_price_input_usd_per_mtok",
        "agent_price_output_usd_per_mtok",
        mode="before",
    )
    @classmethod
    def _empty_string_is_none(cls, value: Any) -> Any:
        """Una variable de entorno vacía (`VAR=`) equivale a «no definida»."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _check_agent_coherence(self) -> Self:
        if self.proposal_target_rr < self.min_rr:
            raise ValueError(
                f"PROPOSAL_TARGET_RR ({self.proposal_target_rr}) debe ser mayor o igual "
                f"que MIN_RR ({self.min_rr})"
            )
        if self.agent_max_cost_usd_per_analysis is not None and (
            self.agent_price_input_usd_per_mtok is None
            or self.agent_price_output_usd_per_mtok is None
        ):
            raise ValueError(
                "AGENT_MAX_COST_USD_PER_ANALYSIS exige definir AGENT_PRICE_INPUT_USD_PER_MTOK "
                "y AGENT_PRICE_OUTPUT_USD_PER_MTOK"
            )
        self._check_model_matches_provider()
        return self

    def _check_model_matches_provider(self) -> None:
        """Un modelo definido explícitamente no puede ser de la familia del otro proveedor."""
        other = {"anthropic": "gemini", "google": "claude"}[self.agent_provider]
        candidates = {
            "AGENT_MODEL": self.agent_model if "agent_model" in self.model_fields_set else None,
            "AGENT_AUDITOR_MODEL": self.agent_auditor_model,
        }
        for var, name in candidates.items():
            if name is not None and name.strip().lower().startswith(other):
                raise ValueError(
                    f"{var}={name!r} no corresponde a AGENT_PROVIDER={self.agent_provider!r}"
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
