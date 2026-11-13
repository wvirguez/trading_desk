"""Tests de `POST /api/v1/quant/backtest`."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy import Strategy
from app.schemas.quant import BacktestMetricsSchema
from tests.services.test_backtest_service import seed

URL = "/api/v1/quant/backtest"
BODY = {"symbol": "EUR/USD", "timeframe": "1h", "zscore_window": 20}

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("use_test_db")]


async def n_rows(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(Strategy))).scalar_one())


async def test_200_esquema_completo(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed(db_session, "EUR/USD", 300)

    response = await client.post(URL, json=BODY)

    assert response.status_code == 200, response.text
    body = response.json()
    parsed = BacktestMetricsSchema.model_validate(body)
    assert parsed.n_bars == 300
    assert body["n_trades"] == parsed.n_trades
    assert len(body["equity_curve"]) == 300
    assert body["warnings"]


async def test_dinero_viaja_como_cadena(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed(db_session, "EUR/USD", 300)

    body = (await client.post(URL, json=BODY)).json()

    assert isinstance(body["final_equity"], str)
    assert all(isinstance(p["equity"], str) for p in body["equity_curve"])
    assert isinstance(body["total_return"], float)


async def test_deja_una_fila_en_strategies(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed(db_session, "EUR/USD", 300)

    body = (await client.post(URL, json=BODY)).json()

    row = (await db_session.execute(select(Strategy))).scalar_one()
    assert str(row.id) == body["strategy_id"]


async def test_404_simbolo_desconocido(client: AsyncClient, db_session: AsyncSession) -> None:
    response = await client.post(URL, json=BODY | {"symbol": "XYZ"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Instrumento desconocido: XYZ"}
    assert await n_rows(db_session) == 0


async def test_422_exit_z_mayor_o_igual_que_entry_z(client: AsyncClient) -> None:
    response = await client.post(URL, json=BODY | {"entry_z": 1.0, "exit_z": 1.0})

    assert response.status_code == 422
    assert "exit_z" in response.text


async def test_422_datos_insuficientes(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed(db_session, "EUR/USD", 21)

    response = await client.post(URL, json=BODY)

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Datos insuficientes para EUR/USD 1h: 21 velas, se necesitan al menos 22."
    )
    assert await n_rows(db_session) == 0
