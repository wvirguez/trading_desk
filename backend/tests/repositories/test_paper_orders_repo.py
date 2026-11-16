"""Tests `db` del repositorio de `paper_orders` (D133, D138)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paper_order import PaperOrder
from app.models.trade_signal import TradeSignal
from app.repositories import instruments as instruments_repo
from app.repositories import paper_orders as repo
from app.schemas.enums import OrderStatus

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 10, tzinfo=UTC)


async def _signal(
    session: AsyncSession, symbol: str = "BTC/USDT", risk: str = "100", units: str | None = "2"
) -> TradeSignal:
    inst = await instruments_repo.get_by_symbol(session, symbol)
    assert inst is not None
    row = TradeSignal(
        id=uuid.uuid4(),
        instrument_id=inst.id,
        timeframe="1h",
        direction="LONG",
        entry=Decimal("100.5"),
        stop_loss=Decimal("95.25"),
        take_profit=Decimal("111"),
        status="APPROVED",
        analysis_id=uuid.uuid4(),
        rr=Decimal("2"),
        units=Decimal(units) if units else None,
        risk_amount=Decimal(risk),
        regime="TRENDING",
    )
    session.add(row)
    await session.flush()
    return row


async def _order(
    session: AsyncSession, executed_at: datetime = T0, symbol: str = "BTC/USDT", risk: str = "100"
) -> PaperOrder:
    return await repo.insert_order(session, await _signal(session, symbol, risk), executed_at)


async def _close(session: AsyncSession, order: PaperOrder, pnl: str, closed_at: datetime) -> None:
    await repo.update_order_state(
        session,
        order,
        status=OrderStatus.CLOSED_TP,
        updated_at=closed_at,
        fill_price=Decimal(100),
        filled_at=closed_at - timedelta(hours=1),
        exit_price=Decimal(110),
        closed_at=closed_at,
        realized_pnl=Decimal(pnl),
    )


async def test_insert_order_copia_niveles_y_tamano(db_session: AsyncSession) -> None:
    sig = await _signal(db_session)
    order = await repo.insert_order(db_session, sig, T0)
    assert order.signal_id == sig.id
    assert order.instrument_id == sig.instrument_id
    assert (order.timeframe, order.direction) == ("1h", "LONG")
    assert order.signal_entry == Decimal("100.5")
    assert (order.stop_loss, order.take_profit) == (Decimal("95.25"), Decimal("111"))
    assert (order.units, order.risk_amount) == (Decimal("2"), Decimal("100"))
    assert order.status == "PENDING_FILL"
    assert order.executed_at == T0
    assert order.fill_price is None
    assert order.id is not None


async def test_insert_order_sin_tamano_falla(db_session: AsyncSession) -> None:
    sig = await _signal(db_session, units=None)
    with pytest.raises(ValueError, match="no tiene tamaño"):
        await repo.insert_order(db_session, sig, T0)


async def test_segunda_orden_para_la_misma_senal_lanza_unicidad(
    db_session: AsyncSession,
) -> None:
    sig = await _signal(db_session)
    await repo.insert_order(db_session, sig, T0)
    with pytest.raises(IntegrityError, match="uq_paper_orders_signal_id"):
        await repo.insert_order(db_session, sig, T0)


async def test_list_open_orders_solo_activas_con_simbolo(db_session: AsyncSession) -> None:
    pending = await _order(db_session, T0)
    opened = await _order(db_session, T0 + timedelta(hours=1), "EUR/USD")
    await repo.update_order_state(
        db_session,
        opened,
        status=OrderStatus.OPEN,
        updated_at=T0,
        fill_price=Decimal(100),
        filled_at=T0,
    )
    closed = await _order(db_session, T0 + timedelta(hours=2))
    await _close(db_session, closed, "10", T0 + timedelta(hours=3))

    rows = await repo.list_open_orders(db_session)
    assert [(o.id, i.symbol) for o, i in rows] == [
        (pending.id, "BTC/USDT"),
        (opened.id, "EUR/USD"),
    ]


async def test_list_orders_orden_desc_filtro_y_limit(db_session: AsyncSession) -> None:
    a = await _order(db_session, T0)
    b = await _order(db_session, T0 + timedelta(hours=2))
    c = await _order(db_session, T0 + timedelta(hours=1))
    await _close(db_session, a, "10", T0 + timedelta(hours=5))

    assert [o.id for o, _ in await repo.list_orders(db_session, None, 10)] == [b.id, c.id, a.id]
    assert [o.id for o, _ in await repo.list_orders(db_session, None, 2)] == [b.id, c.id]
    pend = await repo.list_orders(db_session, OrderStatus.PENDING_FILL, 10)
    assert [o.id for o, _ in pend] == [b.id, c.id]
    assert [i.symbol for _, i in pend] == ["BTC/USDT", "BTC/USDT"]
    assert [o.id for o, _ in await repo.list_orders(db_session, OrderStatus.CLOSED_TP, 10)] == [
        a.id
    ]


async def test_sumas_de_pnl_realizado_en_decimal(db_session: AsyncSession) -> None:
    total0 = await repo.sum_realized_pnl(db_session)
    assert total0 == Decimal(0)
    assert isinstance(total0, Decimal)

    day = datetime(2026, 11, 16, tzinfo=UTC)
    o1, o2, o3, pend = [await _order(db_session, T0) for _ in range(4)]
    await _close(db_session, o1, "10.1234567891", day - timedelta(seconds=1))  # ayer
    await _close(db_session, o2, "-3.5", day)  # inicio incluido
    await _close(db_session, o3, "0.2", day + timedelta(hours=23))
    assert pend.status == "PENDING_FILL"

    total = await repo.sum_realized_pnl(db_session)
    assert total == Decimal("6.8234567891")
    today = await repo.sum_realized_pnl_between(db_session, day, day + timedelta(days=1))
    assert today == Decimal("-3.3")
    assert isinstance(today, Decimal)
    assert await repo.sum_realized_pnl_between(
        db_session, day + timedelta(days=1), day + timedelta(days=2)
    ) == Decimal(0)


async def test_update_order_state_solo_cambia_columnas_de_estado(
    db_session: AsyncSession,
) -> None:
    order = await _order(db_session)
    before = {
        c: getattr(order, c)
        for c in ("signal_entry", "units", "stop_loss", "take_profit", "risk_amount", "signal_id")
    }
    fill_ts = T0 + timedelta(hours=1)
    await repo.update_order_state(
        db_session,
        order,
        status=OrderStatus.OPEN,
        updated_at=fill_ts,
        fill_price=Decimal("100.6"),
        filled_at=fill_ts,
        last_processed_ts=fill_ts,
    )
    await db_session.commit()
    db_session.expire_all()
    raw = (await db_session.execute(text("SELECT * FROM paper_orders"))).one()
    assert (raw.status, raw.fill_price, raw.filled_at) == ("OPEN", Decimal("100.6"), fill_ts)
    assert raw.last_processed_ts == fill_ts
    assert raw.updated_at == fill_ts
    assert raw.exit_price is None
    for col, value in before.items():
        assert getattr(raw, col) == value


async def test_update_order_state_no_admite_columnas_inmutables(
    db_session: AsyncSession,
) -> None:
    order = await _order(db_session)
    with pytest.raises(TypeError):
        await repo.update_order_state(  # type: ignore[call-arg]
            db_session, order, status=OrderStatus.OPEN, updated_at=T0, stop_loss=Decimal(1)
        )


async def test_check_de_coherencia_se_aplica_al_actualizar(db_session: AsyncSession) -> None:
    order = await _order(db_session)
    with pytest.raises(IntegrityError, match="ck_paper_orders_status_state"):
        await repo.update_order_state(
            db_session, order, status=OrderStatus.CLOSED_SL, updated_at=T0
        )


async def test_to_schema_cerrada_y_pendiente(db_session: AsyncSession) -> None:
    order = await _order(db_session, risk="100")
    pend = repo.to_schema(order, "BTC/USDT")
    assert pend.status is OrderStatus.PENDING_FILL
    assert pend.pnl is None
    assert pend.r_multiple is None
    await _close(db_session, order, "-50", T0 + timedelta(hours=3))
    closed = repo.to_schema(order, "BTC/USDT")
    assert closed.realized_pnl == closed.pnl == Decimal(-50)
    assert closed.r_multiple == Decimal("-0.5")
    assert closed.order_id == order.id
    assert closed.symbol == "BTC/USDT"
