"""Tests de `GET /api/v1/signals/active`."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import instruments as instruments_repo
from app.repositories import trade_signals as repo
from app.schemas.enums import (
    AssetClass,
    Direction,
    RegimeLabel,
    SignalStatus,
    Timeframe,
    VetoReason,
)
from app.schemas.risk import PositionSizeResult
from app.schemas.signals import TradeSignalSchema

URL = "/api/v1/signals/active"
T0 = datetime(2026, 11, 1, tzinfo=UTC)

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("use_test_db")]


async def add(
    session: AsyncSession,
    symbol: str = "BTC/USDT",
    asset_class: AssetClass = AssetClass.CRYPTO,
    status: SignalStatus = SignalStatus.APPROVED,
    minutes: int = 0,
) -> TradeSignalSchema:
    approved = status is SignalStatus.APPROVED
    signal = TradeSignalSchema(
        id=uuid.uuid4(),
        analysis_id=uuid.uuid4(),
        symbol=symbol,
        asset_class=asset_class,
        timeframe=Timeframe.H1,
        direction=Direction.LONG,
        entry=Decimal("100.5"),
        stop_loss=Decimal("95.25"),
        take_profit=Decimal("111.0"),
        rr=Decimal("2.0000"),
        size=(
            PositionSizeResult(
                units=Decimal("1.9047619048"),
                risk_amount=Decimal("100.0000000000"),
                risk_pct=Decimal("1"),
                stop_distance=Decimal("5.25"),
                notional=Decimal("191.4285714324"),
            )
            if approved
            else None
        ),
        status=status,
        regime=RegimeLabel.TRENDING,
        rationale="motivo",
        veto_reasons=[] if approved else [VetoReason.RR_BELOW_MIN],
        created_at=T0 + timedelta(minutes=minutes),
    )
    row = await instruments_repo.get_by_symbol(session, symbol)
    assert row is not None
    await repo.insert_signal(session, signal, row.id)
    await session.commit()
    return signal


async def test_vacio_devuelve_lista_vacia(client: AsyncClient, db_session: AsyncSession) -> None:
    response = await client.get(URL)

    assert response.status_code == 200
    assert response.json() == []


async def test_solo_aprobadas(client: AsyncClient, db_session: AsyncSession) -> None:
    ok = await add(db_session)
    await add(db_session, status=SignalStatus.REJECTED, minutes=1)

    body = (await client.get(URL)).json()

    assert [s["id"] for s in body] == [str(ok.id)]
    assert body[0]["status"] == "APPROVED"
    TradeSignalSchema.model_validate(body[0])


async def test_filtro_asset_class(client: AsyncClient, db_session: AsyncSession) -> None:
    await add(db_session, "BTC/USDT", AssetClass.CRYPTO)
    fx = await add(db_session, "EUR/USD", AssetClass.FX, minutes=1)

    body = (await client.get(URL, params={"asset_class": "FX"})).json()

    assert [s["id"] for s in body] == [str(fx.id)]
    assert len((await client.get(URL)).json()) == 2


async def test_asset_class_invalida_es_422(client: AsyncClient) -> None:
    assert (await client.get(URL, params={"asset_class": "BONOS"})).status_code == 422


@pytest.mark.parametrize("limit", [0, -1, 201])
async def test_limit_fuera_de_rango_es_422(client: AsyncClient, limit: int) -> None:
    response = await client.get(URL, params={"limit": limit})

    assert response.status_code == 422
    assert "limit" in response.text


async def test_limit_en_los_bordes_es_valido(client: AsyncClient) -> None:
    for limit in (1, 200):
        assert (await client.get(URL, params={"limit": limit})).status_code == 200


async def test_mas_recientes_primero_y_limit(client: AsyncClient, db_session: AsyncSession) -> None:
    old = await add(db_session, minutes=0)
    new = await add(db_session, minutes=10)
    mid = await add(db_session, minutes=5)

    body = (await client.get(URL)).json()
    assert [s["id"] for s in body] == [str(new.id), str(mid.id), str(old.id)]

    limited = (await client.get(URL, params={"limit": 2})).json()
    assert [s["id"] for s in limited] == [str(new.id), str(mid.id)]


async def test_decimal_viaja_como_cadena(client: AsyncClient, db_session: AsyncSession) -> None:
    await add(db_session)

    signal = (await client.get(URL)).json()[0]

    for field in ("entry", "stop_loss", "take_profit", "rr"):
        assert isinstance(signal[field], str), field
    assert Decimal(signal["entry"]) == Decimal("100.5")
    assert isinstance(signal["size"]["units"], str)
    assert isinstance(signal["size"]["risk_amount"], str)
