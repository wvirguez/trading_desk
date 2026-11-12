from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.db import get_session
from app.main import app
from app.schemas.health import HealthSchema
from tests.conftest import session_override_for

HEALTH_URL = "/api/v1/health"


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _SessionWithoutTimescale:
    """Base de datos accesible, pero sin la extensión timescaledb."""

    async def execute(self, *_args: Any, **_kwargs: Any) -> _FakeResult:
        return _FakeResult(None)


async def _session_without_timescale() -> AsyncIterator[_SessionWithoutTimescale]:
    yield _SessionWithoutTimescale()


async def test_health_returns_503_when_database_is_down(client: AsyncClient) -> None:
    # Puerto 1: conexión rechazada de inmediato, sin necesidad de una BD real.
    app.dependency_overrides[get_session] = session_override_for(
        "postgresql+asyncpg://nobody:nopass@127.0.0.1:1/nodb"
    )

    response = await client.get(HEALTH_URL)

    assert response.status_code == 503
    body = HealthSchema.model_validate(response.json())
    assert body.status == "degraded"
    assert body.database == "error"
    assert body.timescaledb is None


async def test_health_is_degraded_without_timescaledb(client: AsyncClient) -> None:
    app.dependency_overrides[get_session] = _session_without_timescale

    response = await client.get(HEALTH_URL)

    assert response.status_code == 503
    body = HealthSchema.model_validate(response.json())
    assert body.status == "degraded"
    assert body.database == "ok"
    assert body.timescaledb is None


async def test_openapi_exposes_health_schema(client: AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()

    assert "HealthSchema" in spec["components"]["schemas"]
    responses = spec["paths"][HEALTH_URL]["get"]["responses"]
    assert {"200", "503"} <= responses.keys()


@pytest.mark.db
@pytest.mark.usefixtures("use_test_db")
async def test_health_ok_against_real_database(client: AsyncClient) -> None:
    response = await client.get(HEALTH_URL)

    assert response.status_code == 200, response.text
    body = HealthSchema.model_validate(response.json())
    assert body.status == "ok"
    assert body.database == "ok"
    assert body.timescaledb is not None
    assert body.timescaledb.startswith("2.")
