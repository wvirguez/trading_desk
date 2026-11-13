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
