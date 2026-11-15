from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_point_to_local_pg16_cluster(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.database_url.endswith("@localhost:5432/quant_terminal_db")
    assert settings.test_database_url.endswith("/quant_terminal_test")


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/other")
    monkeypatch.setenv("APP_ENV", "test")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/other"
    assert settings.app_env == "test"


def test_oanda_and_backfill_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("OANDA_API_TOKEN", "OANDA_ACCOUNT_ID", "OANDA_BASE_URL"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.oanda_api_token is None
    assert settings.oanda_account_id is None
    assert settings.oanda_base_url == "https://api-fxpractice.oanda.com"
    assert settings.backfill_days_5m == 90
    assert settings.backfill_days_15m == 365
    assert settings.backfill_years_1h == 5
    assert settings.backfill_years_4h == 5
    assert settings.backfill_years_1d == 5


def test_yahoo_backfill_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for tf in ("5M", "15M", "1H", "4H"):
        monkeypatch.delenv(f"BACKFILL_DAYS_{tf}_YAHOO", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.backfill_days_5m_yahoo == 59
    assert settings.backfill_days_15m_yahoo == 59
    assert settings.backfill_days_1h_yahoo == 729
    assert settings.backfill_days_4h_yahoo == 729


def test_yahoo_backfill_is_overridable_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKFILL_DAYS_5M_YAHOO", "30")
    monkeypatch.setenv("BACKFILL_DAYS_5M", "45")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.backfill_days_5m_yahoo == 30
    assert settings.backfill_days_5m == 45


def test_oanda_token_is_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OANDA_API_TOKEN", "token-super-secreto")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.oanda_api_token is not None
    assert settings.oanda_api_token.get_secret_value() == "token-super-secreto"
    assert "token-super-secreto" not in repr(settings)
    assert "token-super-secreto" not in str(settings)


_RISK_VARS = (
    "RISK_PER_TRADE_PCT",
    "MAX_DAILY_LOSS_PCT",
    "MIN_RR",
    "KELLY_FRACTION",
    "MAX_OPEN_RISK_PCT",
    "MAX_CORRELATED_RISK_PCT",
    "CORRELATION_WINDOW",
    "CORRELATION_THRESHOLD",
    "BACKTEST_MAX_BARS",
)


def test_risk_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _RISK_VARS:
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.risk_per_trade_pct == Decimal("1.0")
    assert settings.max_daily_loss_pct == Decimal("3.0")
    assert settings.min_rr == Decimal("1.8")
    assert settings.kelly_fraction == Decimal("0.25")
    assert settings.max_open_risk_pct == Decimal("3.0")
    assert settings.max_correlated_risk_pct == Decimal("2.0")
    assert settings.correlation_window == 100
    assert settings.correlation_threshold == Decimal("0.7")
    assert settings.backtest_max_bars == 50000
    assert isinstance(settings.risk_per_trade_pct, Decimal)


def test_risk_vars_are_overridable_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RISK_PER_TRADE_PCT", "0.5")
    monkeypatch.setenv("MIN_RR", "2")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.risk_per_trade_pct == Decimal("0.5")
    assert settings.min_rr == Decimal("2")


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("RISK_PER_TRADE_PCT", "0"),
        ("RISK_PER_TRADE_PCT", "50"),
        ("MIN_RR", "0.5"),
        ("MAX_DAILY_LOSS_PCT", "0"),
        ("KELLY_FRACTION", "1.5"),
        ("CORRELATION_THRESHOLD", "1.2"),
        ("CORRELATION_WINDOW", "5"),
        ("BACKTEST_MAX_BARS", "0"),
    ],
)
def test_risk_vars_reject_out_of_range(
    monkeypatch: pytest.MonkeyPatch, var: str, value: str
) -> None:
    monkeypatch.setenv(var, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


_AGENT_VARS = (
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "AGENT_PROVIDER",
    "AGENT_MODEL",
    "AGENT_AUDITOR_MODEL",
    "AGENT_TIMEOUT_S",
    "AGENT_MAX_TOKENS_PER_ANALYSIS",
    "AGENT_MAX_COST_USD_PER_ANALYSIS",
    "AGENT_PRICE_INPUT_USD_PER_MTOK",
    "AGENT_PRICE_OUTPUT_USD_PER_MTOK",
    "ACCOUNT_EQUITY_USD",
    "ANALYSIS_LOOKBACK_BARS",
    "PROPOSAL_TARGET_RR",
    "PROPOSAL_SL_ATR_BUFFER",
    "MIN_RR",
)


def _clean_agent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _AGENT_VARS:
        monkeypatch.delenv(var, raising=False)


def test_agent_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_agent_env(monkeypatch)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.agent_provider == "anthropic"
    assert settings.anthropic_api_key is None
    assert settings.gemini_api_key is None
    assert settings.agent_model == "claude-sonnet-5-5"
    assert settings.agent_auditor_model is None
    assert settings.agent_timeout_s == 120
    assert settings.agent_max_tokens_per_analysis == 60000
    assert settings.agent_max_cost_usd_per_analysis is None
    assert settings.agent_price_input_usd_per_mtok is None
    assert settings.agent_price_output_usd_per_mtok is None
    assert settings.account_equity_usd == Decimal("10000")
    assert settings.analysis_lookback_bars == 500
    assert settings.proposal_target_rr == Decimal("2.0")
    assert settings.proposal_sl_atr_buffer == Decimal("0.5")


def test_anthropic_key_is_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-super-secreta")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-super-secreta"
    assert "sk-ant-super-secreta" not in repr(settings)
    assert "sk-ant-super-secreta" not in str(settings)


def test_empty_optional_agent_vars_are_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_agent_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("AGENT_AUDITOR_MODEL", "")
    monkeypatch.setenv("AGENT_MAX_COST_USD_PER_ANALYSIS", "")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.anthropic_api_key is None
    assert settings.agent_auditor_model is None
    assert settings.agent_max_cost_usd_per_analysis is None


def test_proposal_target_rr_below_min_rr_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_agent_env(monkeypatch)
    monkeypatch.setenv("MIN_RR", "1.8")
    monkeypatch.setenv("PROPOSAL_TARGET_RR", "1.0")

    with pytest.raises(ValidationError, match="PROPOSAL_TARGET_RR"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_cost_cap_requires_both_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_agent_env(monkeypatch)
    monkeypatch.setenv("AGENT_MAX_COST_USD_PER_ANALYSIS", "0.5")

    with pytest.raises(ValidationError, match="AGENT_MAX_COST_USD_PER_ANALYSIS"):
        Settings(_env_file=None)  # type: ignore[call-arg]

    monkeypatch.setenv("AGENT_PRICE_INPUT_USD_PER_MTOK", "3")
    with pytest.raises(ValidationError, match="AGENT_MAX_COST_USD_PER_ANALYSIS"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_cost_cap_with_both_prices_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_agent_env(monkeypatch)
    monkeypatch.setenv("AGENT_MAX_COST_USD_PER_ANALYSIS", "0.5")
    monkeypatch.setenv("AGENT_PRICE_INPUT_USD_PER_MTOK", "3")
    monkeypatch.setenv("AGENT_PRICE_OUTPUT_USD_PER_MTOK", "15")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.agent_max_cost_usd_per_analysis == Decimal("0.5")


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("ANALYSIS_LOOKBACK_BARS", "10"),
        ("ANALYSIS_LOOKBACK_BARS", "5001"),
        ("AGENT_TIMEOUT_S", "0"),
        ("AGENT_MAX_TOKENS_PER_ANALYSIS", "0"),
        ("ACCOUNT_EQUITY_USD", "0"),
        ("PROPOSAL_SL_ATR_BUFFER", "-1"),
        ("AGENT_PRICE_INPUT_USD_PER_MTOK", "-1"),
        ("AGENT_MAX_COST_USD_PER_ANALYSIS", "0"),
    ],
)
def test_agent_vars_reject_out_of_range(
    monkeypatch: pytest.MonkeyPatch, var: str, value: str
) -> None:
    _clean_agent_env(monkeypatch)
    monkeypatch.setenv(var, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_gemini_key_is_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_agent_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-super-secreta")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.gemini_api_key is not None
    assert settings.gemini_api_key.get_secret_value() == "AIza-super-secreta"
    assert "AIza-super-secreta" not in repr(settings)
    assert "AIza-super-secreta" not in str(settings)


def test_empty_gemini_key_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_agent_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "  ")

    assert Settings(_env_file=None).gemini_api_key is None  # type: ignore[call-arg]


def test_agent_provider_from_env_and_invalid_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_agent_env(monkeypatch)
    monkeypatch.setenv("AGENT_PROVIDER", "google")
    assert Settings(_env_file=None).agent_provider == "google"  # type: ignore[call-arg]

    monkeypatch.setenv("AGENT_PROVIDER", "openai")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("provider", "model", "auditor"),
    [
        ("google", "claude-sonnet-5-5", None),
        ("google", "gemini-3.8-flash", "claude-x"),
        ("anthropic", "gemini-3.8-flash", None),
        ("anthropic", "claude-sonnet-5-5", "gemini-3.8-flash"),
    ],
)
def test_model_of_the_other_provider_is_rejected(
    monkeypatch: pytest.MonkeyPatch, provider: str, model: str, auditor: str | None
) -> None:
    _clean_agent_env(monkeypatch)
    with pytest.raises(ValidationError, match="no corresponde a AGENT_PROVIDER"):
        Settings(  # type: ignore[call-arg]
            _env_file=None, agent_provider=provider, agent_model=model, agent_auditor_model=auditor
        )


def test_google_with_default_model_is_valid_at_settings_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El modelo por defecto no se valida en Settings; `build_model` exige AGENT_MODEL."""
    _clean_agent_env(monkeypatch)
    settings = Settings(_env_file=None, agent_provider="google")  # type: ignore[call-arg]
    assert "agent_model" not in settings.model_fields_set
