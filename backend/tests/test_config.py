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
