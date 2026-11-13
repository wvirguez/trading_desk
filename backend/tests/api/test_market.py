"""Tests de `GET /api/v1/market/ohlcv`."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.fake import FakeAdapter
from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as repo
from app.schemas.candle import CandleSchema
from app.schemas.enums import Timeframe

URL = "/api/v1/market/ohlcv"
T0 = datetime(2026, 1, 1, tzinfo=UTC)

db = pytest.mark.usefixtures("use_test_db")


async def _seed(session: AsyncSession, symbol: str, n: int) -> list[CandleSchema]:
    row = await instruments_repo.get_by_symbol(session, symbol)
    assert row is not None
    adapter = FakeAdapter(seed=1, now=lambda: T0 + timedelta(days=365))
    candles = await adapter.fetch_ohlcv(
        instruments_repo.to_schema(row), Timeframe.H1, T0, T0 + timedelta(hours=n)
    )
    await repo.upsert_candles(session, row.id, candles)
    await session.commit()
    return candles


@pytest.mark.db
@db
async def test_devuelve_ultimas_velas_en_orden_ascendente(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seeded = await _seed(db_session, "BTC/USDT", 30)

    response = await client.get(URL, params={"symbol": "BTC/USDT", "tf": "1h", "limit": 10})

    assert response.status_code == 200, response.text
    body = [CandleSchema.model_validate(item) for item in response.json()]
    assert len(body) == 10
    assert body == seeded[-10:]
    assert [c.ts for c in body] == sorted(c.ts for c in body)


@pytest.mark.db
@db
async def test_limite_por_defecto_devuelve_todas_si_hay_menos(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed(db_session, "BTC/USDT", 12)

    response = await client.get(URL, params={"symbol": "BTC/USDT", "tf": "1h"})

    assert response.status_code == 200
    assert len(response.json()) == 12


@pytest.mark.db
@db
async def test_lista_vacia_sin_velas(client: AsyncClient, db_session: AsyncSession) -> None:
    response = await client.get(URL, params={"symbol": "BTC/USDT", "tf": "1h"})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.db
@db
async def test_precios_como_cadena_con_precision_intacta(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    row = await instruments_repo.get_by_symbol(db_session, "BTC/USDT")
    assert row is not None
    candle = CandleSchema(
        symbol="BTC/USDT",
        timeframe=Timeframe.H1,
        ts=T0,
        open=Decimal("100.12345678"),
        high=Decimal("110.5"),
        low=Decimal("90.00000001"),
        close=Decimal("105.1"),
        volume=Decimal("12.5"),
    )
    await repo.upsert_candles(db_session, row.id, [candle])
    await db_session.commit()

    response = await client.get(URL, params={"symbol": "BTC/USDT", "tf": "1h"})

    item = response.json()[0]
    for field in ("open", "high", "low", "close", "volume"):
        assert isinstance(item[field], str)
    # La columna NUMERIC puede rellenar con ceros; el valor exacto no debe cambiar.
    assert item["open"].startswith("100.12345678")
    assert Decimal(item["open"]) == Decimal("100.12345678")
    assert Decimal(item["low"]) == Decimal("90.00000001")
    assert Decimal(item["close"]) == Decimal("105.1")


@pytest.mark.db
@db
async def test_simbolo_desconocido_404(client: AsyncClient) -> None:
    response = await client.get(URL, params={"symbol": "XYZ", "tf": "1h"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Instrumento desconocido: XYZ"


@pytest.mark.parametrize(
    "params",
    [
        {"symbol": "BTC/USDT", "tf": "2h"},
        {"symbol": "BTC/USDT", "tf": "1h", "limit": 0},
        {"symbol": "BTC/USDT", "tf": "1h", "limit": 5001},
        {"symbol": "BTC/USDT", "tf": "1h", "limit": "abc"},
        {"tf": "1h"},
        {"symbol": "BTC/USDT"},
    ],
)
async def test_parametros_invalidos_422(client: AsyncClient, params: dict[str, str | int]) -> None:
    # La validación ocurre antes de abrir la sesión: no necesita base de datos.
    response = await client.get(URL, params=params)

    assert response.status_code == 422


async def test_openapi_expone_candle_schema(client: AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()

    assert "CandleSchema" in spec["components"]["schemas"]
    assert "get" in spec["paths"][URL]
