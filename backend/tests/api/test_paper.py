"""Tests de `POST /signals/{id}/execute`, `POST /paper/refresh` y `GET /paper/blotter`."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as ohlcv_repo
from app.repositories import paper_orders as orders_repo
from app.repositories import trade_signals as signals_repo
from app.schemas.candle import CandleSchema
from app.schemas.enums import (
    AssetClass,
    Direction,
    OrderStatus,
    RegimeLabel,
    SignalStatus,
    Timeframe,
    VetoReason,
)
from app.schemas.paper import BlotterSchema, OrderReceiptSchema, PaperRefreshResult
from app.schemas.risk import PositionSizeResult
from app.schemas.signals import TradeSignalSchema

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("use_test_db")]

H = timedelta(hours=1)


async def add_signal(
    session: AsyncSession,
    status: SignalStatus = SignalStatus.APPROVED,
    symbol: str = "EUR/USD",
    risk: str = "100",
    created_at: datetime | None = None,
) -> TradeSignalSchema:
    approved = status in (SignalStatus.APPROVED, SignalStatus.EXECUTED)
    signal = TradeSignalSchema(
        id=uuid.uuid4(),
        analysis_id=uuid.uuid4(),
        symbol=symbol,
        asset_class=AssetClass.FX if symbol == "EUR/USD" else AssetClass.CRYPTO,
        timeframe=Timeframe.H1,
        direction=Direction.SHORT,
        entry=Decimal("1.1"),
        stop_loss=Decimal("1.11"),
        take_profit=Decimal("1.08"),
        rr=Decimal("2.0000"),
        size=(
            PositionSizeResult(
                units=Decimal(10),
                risk_amount=Decimal(risk),
                risk_pct=Decimal(1),
                stop_distance=Decimal("0.01"),
                notional=Decimal(11),
            )
            if approved
            else None
        ),
        status=status,
        regime=RegimeLabel.TRENDING,
        rationale="motivo",
        veto_reasons=[] if approved else [VetoReason.RR_BELOW_MIN],
        created_at=created_at or datetime.now(UTC),
    )
    row = await instruments_repo.get_by_symbol(session, symbol)
    assert row is not None
    await signals_repo.insert_signal(session, signal, row.id)
    await session.commit()
    return signal


def execute_url(signal_id: uuid.UUID | str) -> str:
    return f"/api/v1/signals/{signal_id}/execute"


async def test_execute_devuelve_201_con_recibo(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    signal = await add_signal(db_session)

    response = await client.post(execute_url(signal.id))

    assert response.status_code == 201
    body = response.json()
    receipt = OrderReceiptSchema.model_validate(body)
    assert receipt.simulated is True and body["simulated"] is True
    assert receipt.signal_id == signal.id and receipt.status is OrderStatus.PENDING_FILL
    assert body["units"] == "10.0000000000" and body["risk_amount"] == "100.0000000000"
    assert isinstance(body["signal_entry"], str) and isinstance(body["stop_loss"], str)


async def test_execute_senal_desconocida_404(client: AsyncClient, db_session: AsyncSession) -> None:
    missing = uuid.uuid4()

    response = await client.post(execute_url(missing))

    assert response.status_code == 404
    assert response.json()["detail"] == f"Señal desconocida: {missing}"


async def test_execute_uuid_invalido_422(client: AsyncClient, db_session: AsyncSession) -> None:
    response = await client.post(execute_url("no-es-uuid"))

    assert response.status_code == 422


async def test_execute_senal_rechazada_409(client: AsyncClient, db_session: AsyncSession) -> None:
    signal = await add_signal(db_session, SignalStatus.REJECTED)

    response = await client.post(execute_url(signal.id))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        f"La señal {signal.id} no está aprobada (estado: REJECTED)."
    )


async def test_execute_segunda_vez_409_sin_duplicar(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    signal = await add_signal(db_session)
    assert (await client.post(execute_url(signal.id))).status_code == 201

    response = await client.post(execute_url(signal.id))

    assert response.status_code == 409
    assert response.json()["detail"] == f"La señal {signal.id} ya fue ejecutada."
    assert len((await client.get("/api/v1/paper/blotter")).json()["orders"]) == 1


async def test_execute_veto_de_cartera_409(client: AsyncClient, db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    closed = await add_signal(db_session, SignalStatus.EXECUTED)
    sig_row = await signals_repo.get_signal_for_update(db_session, closed.id)
    assert sig_row is not None
    order = await orders_repo.insert_order(db_session, sig_row, now - 2 * H)
    await orders_repo.update_order_state(
        db_session,
        order,
        status=OrderStatus.CLOSED_SL,
        updated_at=now,
        fill_price=Decimal("1.1"),
        filled_at=now - H,
        exit_price=Decimal("1.11"),
        closed_at=now,
        realized_pnl=Decimal(-300),
        last_processed_ts=now,
    )
    await db_session.commit()
    signal = await add_signal(db_session)

    response = await client.post(execute_url(signal.id))

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "DAILY_LOSS_LIMIT" in detail and "3.00 %" in detail and "UTC" in detail
    active = (await client.get("/api/v1/signals/active")).json()
    assert [s["id"] for s in active] == [str(signal.id)]  # sigue APPROVED


async def test_senal_ejecutada_ya_no_esta_activa(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    signal = await add_signal(db_session)
    assert len((await client.get("/api/v1/signals/active")).json()) == 1

    await client.post(execute_url(signal.id))

    assert (await client.get("/api/v1/signals/active")).json() == []


async def test_refresh_devuelve_contadores(client: AsyncClient, db_session: AsyncSession) -> None:
    signal = await add_signal(db_session)
    t0 = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - H
    await client.post(execute_url(signal.id))
    instrument = await instruments_repo.get_by_symbol(db_session, "EUR/USD")
    assert instrument is not None
    # Vela posterior a la ejecución: la orden se rellena al open.
    await ohlcv_repo.upsert_candles(
        db_session,
        instrument.id,
        [
            CandleSchema(
                symbol="EUR/USD",
                timeframe=Timeframe.H1,
                ts=t0 + 2 * H,
                open=Decimal("1.1"),
                high=Decimal("1.102"),
                low=Decimal("1.09"),
                close=Decimal("1.095"),
                volume=Decimal(1),
            )
        ],
    )
    await db_session.commit()

    response = await client.post("/api/v1/paper/refresh")
    again = await client.post("/api/v1/paper/refresh")

    assert response.status_code == 200
    result = PaperRefreshResult.model_validate(response.json())
    assert (result.orders_checked, result.orders_filled, result.orders_closed) == (1, 1, 0)
    assert PaperRefreshResult.model_validate(again.json()).orders_filled == 0


async def test_blotter_vacio_y_decimales_como_cadena(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    signal = await add_signal(db_session)
    await client.post(execute_url(signal.id))

    response = await client.get("/api/v1/paper/blotter")

    assert response.status_code == 200
    body = response.json()
    blotter = BlotterSchema.model_validate(body)
    assert len(blotter.orders) == 1 and blotter.daily_loss_limit_reached is False
    for key in ("equity", "day_start_equity", "open_risk", "realized_pnl_total"):
        assert isinstance(body[key], str)
    assert body["open_risk"] == "100.0000000000"


async def test_blotter_filtra_por_estado(client: AsyncClient, db_session: AsyncSession) -> None:
    signal = await add_signal(db_session)
    await client.post(execute_url(signal.id))

    pendientes = (
        await client.get("/api/v1/paper/blotter", params={"status": "PENDING_FILL"})
    ).json()
    cerradas = (await client.get("/api/v1/paper/blotter", params={"status": "CLOSED_TP"})).json()

    assert len(pendientes["orders"]) == 1 and cerradas["orders"] == []


async def test_blotter_no_modifica_datos(client: AsyncClient, db_session: AsyncSession) -> None:
    signal = await add_signal(db_session)
    await client.post(execute_url(signal.id))
    before = await orders_repo.get_by_signal(db_session, signal.id)
    assert before is not None
    snapshot = (before.status, before.updated_at, before.last_processed_ts)

    first = await client.get("/api/v1/paper/blotter")
    second = await client.get("/api/v1/paper/blotter")

    assert first.json() == second.json()
    await db_session.refresh(before)
    assert (before.status, before.updated_at, before.last_processed_ts) == snapshot


@pytest.mark.parametrize("limit", [0, 501, -1])
async def test_blotter_rechaza_limit_fuera_de_rango(
    client: AsyncClient, db_session: AsyncSession, limit: int
) -> None:
    response = await client.get("/api/v1/paper/blotter", params={"limit": limit})

    assert response.status_code == 422
