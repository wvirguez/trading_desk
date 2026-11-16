"""Tests de `GET /api/v1/market/*`."""

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
from app.schemas.instrument import InstrumentSchema
from app.schemas.quant import MarketStructureResult

URL_OHLCV = "/api/v1/market/ohlcv"
URL_INSTRUMENTS = "/api/v1/market/instruments"
URL_STRUCTURE = "/api/v1/market/structure"
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


async def _seed_candles(
    session: AsyncSession, symbol: str, n: int, tf: Timeframe = Timeframe.H1
) -> list[CandleSchema]:
    row = await instruments_repo.get_by_symbol(session, symbol)
    assert row is not None
    step = tf.duration
    candles = [
        CandleSchema(
            symbol=symbol,
            timeframe=tf,
            ts=T0 + step * i,
            open=Decimal("100"),
            high=Decimal("200"),
            low=Decimal("50"),
            close=Decimal(str(100 + (i % 50))),
            volume=Decimal("12.5"),
        )
        for i in range(n)
    ]
    await repo.upsert_candles(session, row.id, candles)
    await session.commit()
    return candles


@pytest.mark.db
@db
async def test_devuelve_ultimas_velas_en_orden_ascendente(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seeded = await _seed(db_session, "BTC/USDT", 30)

    response = await client.get(URL_OHLCV, params={"symbol": "BTC/USDT", "tf": "1h", "limit": 10})

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

    response = await client.get(URL_OHLCV, params={"symbol": "BTC/USDT", "tf": "1h"})

    assert response.status_code == 200
    assert len(response.json()) == 12


@pytest.mark.db
@db
async def test_lista_vacia_sin_velas(client: AsyncClient, db_session: AsyncSession) -> None:
    response = await client.get(URL_OHLCV, params={"symbol": "BTC/USDT", "tf": "1h"})

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

    response = await client.get(URL_OHLCV, params={"symbol": "BTC/USDT", "tf": "1h"})

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
    response = await client.get(URL_OHLCV, params={"symbol": "XYZ", "tf": "1h"})

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
    response = await client.get(URL_OHLCV, params=params)

    assert response.status_code == 422


async def test_openapi_expone_candle_schema(client: AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()

    assert "CandleSchema" in spec["components"]["schemas"]
    assert "get" in spec["paths"][URL_OHLCV]


# --- GET /market/instruments ----------------------------------------------------


@pytest.mark.db
@db
async def test_instruments_devuelve_4_instrumentos_decimal_como_cadena(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.get(URL_INSTRUMENTS)

    assert response.status_code == 200, response.text
    body = [InstrumentSchema.model_validate(item) for item in response.json()]
    assert len(body) == 4
    symbols = {i.symbol for i in body}
    assert symbols == {"BTC/USDT", "EUR/USD", "XAU/USD", "NAS100"}
    # tick_size y lot_size viajan como cadena
    for item in response.json():
        for field in ("tick_size", "lot_size"):
            assert isinstance(item[field], str), field


# --- GET /market/structure ------------------------------------------------------


@pytest.mark.db
@db
async def test_structure_esquema_completo(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_candles(db_session, "EUR/USD", 100)

    response = await client.get(URL_STRUCTURE, params={"symbol": "EUR/USD", "tf": "1h", "n": 3})

    assert response.status_code == 200, response.text
    parsed = MarketStructureResult.model_validate(response.json())
    assert isinstance(parsed.swings, list)
    assert isinstance(parsed.events, list)
    assert isinstance(parsed.fvgs, list)
    # Decimal viaja como cadena
    if parsed.swings:
        assert isinstance(parsed.swings[0].price, Decimal)
        assert isinstance(response.json()["swings"][0]["price"], str)


@pytest.mark.db
@db
async def test_structure_simbolo_desconocido_404(client: AsyncClient) -> None:
    response = await client.get(URL_STRUCTURE, params={"symbol": "XYZ", "tf": "1h", "n": 3})

    assert response.status_code == 404
    assert response.json()["detail"] == "Instrumento desconocido: XYZ"


@pytest.mark.db
@db
async def test_structure_datos_insuficientes_422_con_cantidades(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # n=3 requiere 2*3+1 = 7 velas; sembramos 6
    await _seed_candles(db_session, "EUR/USD", 6)

    response = await client.get(URL_STRUCTURE, params={"symbol": "EUR/USD", "tf": "1h", "n": 3})

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "Datos insuficientes" in detail
    assert "6 velas" in detail
    assert "7" in detail


@pytest.mark.parametrize("n", [0, 11, -1, 100])
async def test_structure_n_fuera_de_rango_422(client: AsyncClient, n: int) -> None:
    response = await client.get(URL_STRUCTURE, params={"symbol": "EUR/USD", "tf": "1h", "n": n})

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "params",
    [
        {"symbol": "EUR/USD", "tf": "2h"},  # timeframe inválido
        {"tf": "1h"},  # falta symbol
        {"symbol": "EUR/USD"},  # falta tf
    ],
)
async def test_structure_parametros_invalidos_422(
    client: AsyncClient, params: dict[str, str | int]
) -> None:
    response = await client.get(URL_STRUCTURE, params=params)

    assert response.status_code == 422


async def test_openapi_expone_marketstructure_y_instrument_schema(client: AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()

    assert "MarketStructureResult" in spec["components"]["schemas"]
    assert "InstrumentSchema" in spec["components"]["schemas"]
    assert "get" in spec["paths"][URL_INSTRUMENTS]
    assert "get" in spec["paths"][URL_STRUCTURE]
