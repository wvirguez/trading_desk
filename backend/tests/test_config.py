import pytest

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
    assert settings.backfill_days_15m == 365
    assert settings.backfill_years_1h == 5
    assert settings.backfill_years_4h == 5
    assert settings.backfill_years_1d == 5


def test_oanda_token_is_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OANDA_API_TOKEN", "token-super-secreto")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.oanda_api_token is not None
    assert settings.oanda_api_token.get_secret_value() == "token-super-secreto"
    assert "token-super-secreto" not in repr(settings)
    assert "token-super-secreto" not in str(settings)
