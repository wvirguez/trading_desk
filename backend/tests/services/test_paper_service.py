"""Tests `db` de `refresh_orders` (D135): avance de órdenes con velas ingeridas."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import build_engine
from app.paper.journal import JournalInput, JournalOrderInput, build_journal
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
from app.schemas.risk import PositionSizeResult
from app.schemas.signals import TradeSignalSchema
from app.services import paper as paper_service
from app.services.backtest import InstrumentNotFoundError
from app.services.paper import (
    ExecutionVetoedError,
    SignalNotExecutableError,
    SignalNotFoundError,
    execute_signal,
    get_blotter,
    get_journal,
    refresh_orders,
)

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("use_test_db")]

T0 = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)
H = timedelta(hours=1)


def _signal() -> TradeSignalSchema:
    return TradeSignalSchema(
        id=uuid.uuid4(),
        analysis_id=uuid.uuid4(),
        symbol="EUR/USD",
        asset_class=AssetClass.FX,
        timeframe=Timeframe.H1,
        direction=Direction.SHORT,
        entry=Decimal("1.1"),
        stop_loss=Decimal("1.11"),
        take_profit=Decimal("1.08"),
        rr=Decimal(2),
        size=PositionSizeResult(
            units=Decimal(10),
            risk_amount=Decimal(100),
            risk_pct=Decimal(1),
            stop_distance=Decimal("0.01"),
            notional=Decimal(11),
        ),
        status=SignalStatus.EXECUTED,
        regime=RegimeLabel.TRENDING,
        rationale="prueba",
        veto_reasons=[],
        created_at=T0,
    )


def _candle(ts: datetime, o: str, h: str, low: str, c: str) -> CandleSchema:
    return CandleSchema(
        symbol="EUR/USD", timeframe=Timeframe.H1, ts=ts,
        open=Decimal(o), high=Decimal(h), low=Decimal(low), close=Decimal(c), volume=Decimal(1),
    )  # fmt: skip


async def _new_order(session: AsyncSession) -> tuple[int, uuid.UUID]:
    row = await instruments_repo.get_by_symbol(session, "EUR/USD")
    assert row is not None
    signal = await signals_repo.insert_signal(session, _signal(), row.id)
    order = await orders_repo.insert_order(session, signal, T0)
    await session.commit()
    return row.id, order.id


async def test_sin_velas_posteriores_no_cambia_nada(db_session: AsyncSession) -> None:
    instrument_id, _ = await _new_order(db_session)
    await ohlcv_repo.upsert_candles(
        db_session, instrument_id, [_candle(T0 - H, "1.1", "1.2", "1.0", "1.1")]
    )
    await db_session.commit()

    result = await refresh_orders(db_session, T0)

    assert (result.orders_checked, result.orders_filled, result.orders_closed) == (1, 0, 0)
    [(order, _)] = await orders_repo.list_open_orders(db_session)
    assert order.status == OrderStatus.PENDING_FILL.value and order.last_processed_ts is None


async def test_sin_ordenes_abiertas_devuelve_ceros(db_session: AsyncSession) -> None:
    result = await refresh_orders(db_session)

    assert (result.orders_checked, result.orders_filled, result.orders_closed) == (0, 0, 0)


async def test_pending_fill_pasa_a_open_y_es_idempotente(db_session: AsyncSession) -> None:
    instrument_id, _ = await _new_order(db_session)
    await ohlcv_repo.upsert_candles(
        db_session, instrument_id, [_candle(T0, "1.1", "1.102", "1.099", "1.1")]
    )
    await db_session.commit()

    first = await refresh_orders(db_session, T0 + H)
    second = await refresh_orders(db_session, T0 + 2 * H)

    assert (first.orders_filled, first.orders_closed) == (1, 0)
    assert (second.orders_checked, second.orders_filled, second.orders_closed) == (1, 0, 0)
    [(order, _)] = await orders_repo.list_open_orders(db_session)
    assert order.status == OrderStatus.OPEN.value
    assert order.fill_price == Decimal("1.1") and order.filled_at == T0
    assert order.last_processed_ts == T0


async def test_orden_con_velas_posteriores_llega_a_cerrada(db_session: AsyncSession) -> None:
    instrument_id, _ = await _new_order(db_session)
    await ohlcv_repo.upsert_candles(
        db_session,
        instrument_id,
        [
            _candle(T0, "1.1", "1.102", "1.099", "1.1"),
            _candle(T0 + H, "1.1", "1.101", "1.079", "1.08"),  # toca el TP (SHORT)
        ],
    )
    await db_session.commit()

    first = await refresh_orders(db_session, T0 + 3 * H)
    second = await refresh_orders(db_session, T0 + 4 * H)

    assert (first.orders_checked, first.orders_filled, first.orders_closed) == (1, 1, 1)
    assert (second.orders_checked, second.orders_filled, second.orders_closed) == (0, 0, 0)
    assert await orders_repo.list_open_orders(db_session) == []
    assert await orders_repo.sum_realized_pnl(db_session) == Decimal("0.2")


async def test_el_avance_es_incremental_entre_llamadas(db_session: AsyncSession) -> None:
    instrument_id, _ = await _new_order(db_session)
    await ohlcv_repo.upsert_candles(
        db_session, instrument_id, [_candle(T0, "1.1", "1.102", "1.099", "1.1")]
    )
    await db_session.commit()
    await refresh_orders(db_session, T0 + H)

    await ohlcv_repo.upsert_candles(
        db_session,
        instrument_id,
        [_candle(T0 + H, "1.1", "1.12", "1.09", "1.11")],  # toca el SL
    )
    await db_session.commit()
    result = await refresh_orders(db_session, T0 + 2 * H)

    assert (result.orders_filled, result.orders_closed) == (0, 1)
    assert await orders_repo.sum_realized_pnl(db_session) == Decimal("-0.1")


async def test_mas_velas_que_la_pagina_no_pierde_las_primeras(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con más velas que el tope por lectura se procesan TODAS, de la más antigua a la reciente."""
    monkeypatch.setattr(paper_service, "_PAGE_SIZE", 2)
    instrument_id, _ = await _new_order(db_session)
    await ohlcv_repo.upsert_candles(
        db_session,
        instrument_id,
        [
            _candle(T0, "1.1", "1.102", "1.099", "1.1"),  # fill (SHORT en 1.1)
            _candle(T0 + H, "1.1", "1.105", "1.095", "1.1"),
            _candle(T0 + 2 * H, "1.1", "1.109", "1.09", "1.1"),
            _candle(T0 + 3 * H, "1.1", "1.101", "1.079", "1.08"),  # toca el TP (SHORT)
            _candle(T0 + 4 * H, "1.1", "1.12", "1.09", "1.11"),  # SL, pero ya cerrada antes
        ],
    )
    await db_session.commit()

    result = await refresh_orders(db_session, T0 + 6 * H)

    assert (result.orders_checked, result.orders_filled, result.orders_closed) == (1, 1, 1)
    assert await orders_repo.list_open_orders(db_session) == []
    assert await orders_repo.sum_realized_pnl(db_session) == Decimal("0.2")  # TP, no SL


async def test_paginado_equivale_a_una_sola_lectura(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El estado con paginas de 2 velas es el mismo que con una sola lectura (sin cierre)."""
    monkeypatch.setattr(paper_service, "_PAGE_SIZE", 2)
    instrument_id, _ = await _new_order(db_session)
    await ohlcv_repo.upsert_candles(
        db_session,
        instrument_id,
        [_candle(T0 + i * H, "1.1", "1.102", "1.099", "1.1") for i in range(5)],
    )
    await db_session.commit()

    result = await refresh_orders(db_session, T0 + 6 * H)

    assert (result.orders_filled, result.orders_closed) == (1, 0)
    [(order, _)] = await orders_repo.list_open_orders(db_session)
    assert order.status == OrderStatus.OPEN.value
    assert order.filled_at == T0 and order.last_processed_ts == T0 + 4 * H


# --- execute_signal, get_blotter y get_journal (grupo 5) ---

SETTINGS = Settings(_env_file=None)  # type: ignore[call-arg]


async def _approved(
    session: AsyncSession,
    *,
    units: str = "10",
    risk: str = "100",
    symbol: str = "EUR/USD",
    direction: Direction = Direction.SHORT,
    status: SignalStatus = SignalStatus.APPROVED,
) -> uuid.UUID:
    base = _signal()
    entry, sl, tp = (
        (Decimal("1.1"), Decimal("1.11"), Decimal("1.08"))
        if direction is Direction.SHORT
        else (Decimal("1.1"), Decimal("1.09"), Decimal("1.12"))
    )
    asset = {"EUR/USD": AssetClass.FX, "XAU/USD": AssetClass.METAL}.get(symbol, AssetClass.CRYPTO)
    signal = base.model_copy(
        update={
            "symbol": symbol,
            "asset_class": asset,
            "direction": direction,
            "entry": entry,
            "stop_loss": sl,
            "take_profit": tp,
            "status": status,
            "size": PositionSizeResult(
                units=Decimal(units),
                risk_amount=Decimal(risk),
                risk_pct=Decimal(1),
                stop_distance=Decimal("0.01"),
                notional=Decimal(11),
            ),
            "created_at": datetime.now(UTC),
        }
    )
    row = await instruments_repo.get_by_symbol(session, symbol)
    assert row is not None
    await signals_repo.insert_signal(session, signal, row.id)
    await session.commit()
    return signal.id


async def _closed_loss(session: AsyncSession, pnl: str, closed_at: datetime) -> None:
    """Orden ya cerrada por SL con `realized_pnl = pnl` (para el circuito de pérdida diaria)."""
    sid = await _approved(session, status=SignalStatus.EXECUTED)
    signal = await signals_repo.get_signal_for_update(session, sid)
    assert signal is not None
    order = await orders_repo.insert_order(session, signal, closed_at - 2 * H)
    await orders_repo.update_order_state(
        session,
        order,
        status=OrderStatus.CLOSED_SL,
        updated_at=closed_at,
        fill_price=Decimal("1.1"),
        filled_at=closed_at - H,
        exit_price=Decimal("1.11"),
        closed_at=closed_at,
        realized_pnl=Decimal(pnl),
        last_processed_ts=closed_at,
    )
    await session.commit()


async def _open_order(session: AsyncSession, symbol: str = "EUR/USD", risk: str = "100") -> None:
    sid = await _approved(session, symbol=symbol, risk=risk, status=SignalStatus.EXECUTED)
    signal = await signals_repo.get_signal_for_update(session, sid)
    assert signal is not None
    await orders_repo.insert_order(session, signal, T0)
    await session.commit()


async def test_execute_crea_orden_con_datos_de_la_senal(db_session: AsyncSession) -> None:
    sid = await _approved(db_session, units="7", risk="70")

    receipt = await execute_signal(db_session, SETTINGS, sid, T0)
    await db_session.commit()

    assert receipt.signal_id == sid and receipt.simulated is True
    assert receipt.status is OrderStatus.PENDING_FILL
    assert receipt.units == Decimal(7)  # el de la señal, no recalculado (D137)
    assert receipt.risk_amount == Decimal(70)
    assert (receipt.signal_entry, receipt.stop_loss, receipt.take_profit) == (
        Decimal("1.1"),
        Decimal("1.11"),
        Decimal("1.08"),
    )
    signal = await signals_repo.get_signal_for_update(db_session, sid)
    assert signal is not None and signal.status == SignalStatus.EXECUTED.value
    order = await orders_repo.get_by_signal(db_session, sid)
    assert order is not None and order.units == Decimal(7) and order.executed_at == T0


async def test_execute_units_no_se_recalcula_aunque_el_equity_cambie(
    db_session: AsyncSession,
) -> None:
    sid = await _approved(db_session, units="3", risk="30")
    settings = Settings(_env_file=None, account_equity_usd=Decimal(50000))  # type: ignore[call-arg]

    receipt = await execute_signal(db_session, settings, sid, T0)

    assert receipt.units == Decimal(3) and receipt.risk_amount == Decimal(30)


@pytest.mark.parametrize("status", [SignalStatus.REJECTED, SignalStatus.PENDING])
async def test_execute_senal_no_aprobada(db_session: AsyncSession, status: SignalStatus) -> None:
    sid = await _approved(db_session, status=status)

    with pytest.raises(SignalNotExecutableError, match=status.value) as exc:
        await execute_signal(db_session, SETTINGS, sid, T0)

    assert exc.value.status is status and str(sid) in str(exc.value)
    assert await orders_repo.get_by_signal(db_session, sid) is None


async def test_execute_senal_ya_ejecutada(db_session: AsyncSession) -> None:
    sid = await _approved(db_session)
    await execute_signal(db_session, SETTINGS, sid, T0)
    await db_session.commit()

    with pytest.raises(SignalNotExecutableError, match="ya fue ejecutada"):
        await execute_signal(db_session, SETTINGS, sid, T0)


async def test_execute_senal_inexistente(db_session: AsyncSession) -> None:
    missing = uuid.uuid4()

    with pytest.raises(SignalNotFoundError, match=f"Señal desconocida: {missing}"):
        await execute_signal(db_session, SETTINGS, missing, T0)


async def _assert_vetoed(
    session: AsyncSession, sid: uuid.UUID, expected: VetoReason, now: datetime = T0
) -> None:
    with pytest.raises(ExecutionVetoedError) as exc:
        await execute_signal(session, SETTINGS, sid, now)
    assert expected in exc.value.reasons
    assert len(exc.value.messages) == len(exc.value.reasons)
    assert expected.value in str(exc.value) and "%" in str(exc.value)
    await session.rollback()
    assert await orders_repo.get_by_signal(session, sid) is None
    signal = await signals_repo.get_signal_for_update(session, sid)
    assert signal is not None and signal.status == SignalStatus.APPROVED.value


async def test_execute_veto_por_perdida_diaria(db_session: AsyncSession) -> None:
    await _closed_loss(db_session, "-300", T0 - H)  # -3 % de 10000, hoy (UTC)
    sid = await _approved(db_session)

    await _assert_vetoed(db_session, sid, VetoReason.DAILY_LOSS_LIMIT)


async def test_execute_perdida_de_ayer_no_veta(db_session: AsyncSession) -> None:
    await _closed_loss(db_session, "-300", T0 - timedelta(days=1))
    sid = await _approved(db_session)

    receipt = await execute_signal(db_session, SETTINGS, sid, T0)

    assert receipt.status is OrderStatus.PENDING_FILL


async def test_execute_veto_por_riesgo_abierto(db_session: AsyncSession) -> None:
    for symbol in ("EUR/USD", "BTC/USDT", "XAU/USD"):
        await _open_order(db_session, symbol)  # 3 x 100 = 3 % (el límite)
    sid = await _approved(db_session, symbol="BTC/USDT")

    await _assert_vetoed(db_session, sid, VetoReason.OPEN_RISK_LIMIT)


async def test_execute_veto_por_riesgo_correlacionado(db_session: AsyncSession) -> None:
    await _open_order(db_session, "EUR/USD", "150")  # mismo símbolo y dirección: rho = 1
    sid = await _approved(db_session, risk="100")  # 150 + 100 > 2 % (200)

    await _assert_vetoed(db_session, sid, VetoReason.CORRELATED_RISK_LIMIT)


async def test_execute_con_velas_posteriores_deja_orden_open(db_session: AsyncSession) -> None:
    sid = await _approved(db_session)
    instrument = await instruments_repo.get_by_symbol(db_session, "EUR/USD")
    assert instrument is not None
    await ohlcv_repo.upsert_candles(
        db_session, instrument.id, [_candle(T0, "1.1", "1.102", "1.09", "1.095")]
    )
    await db_session.commit()

    receipt = await execute_signal(db_session, SETTINGS, sid, T0)

    assert receipt.status is OrderStatus.OPEN
    assert receipt.fill_price == Decimal("1.1") and receipt.filled_at == T0


async def test_execute_con_velas_posteriores_puede_cerrar(db_session: AsyncSession) -> None:
    sid = await _approved(db_session)
    instrument = await instruments_repo.get_by_symbol(db_session, "EUR/USD")
    assert instrument is not None
    await ohlcv_repo.upsert_candles(
        db_session,
        instrument.id,
        [
            _candle(T0, "1.1", "1.102", "1.09", "1.095"),
            _candle(T0 + H, "1.09", "1.095", "1.079", "1.08"),  # TP
        ],
    )
    await db_session.commit()

    receipt = await execute_signal(db_session, SETTINGS, sid, T0)
    await db_session.commit()

    assert receipt.status is OrderStatus.CLOSED_TP
    assert await orders_repo.sum_realized_pnl(db_session) == Decimal("0.2")


async def test_execute_concurrente_crea_una_orden_y_un_error(db_session: AsyncSession) -> None:
    sid = await _approved(db_session)
    engine = build_engine(get_settings().test_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def attempt() -> object:
        async with maker() as session:
            try:
                receipt = await execute_signal(session, SETTINGS, sid, T0)
                await asyncio.sleep(0.2)  # mantiene el bloqueo antes de confirmar
                await session.commit()
                return receipt
            except SignalNotExecutableError as exc:
                return exc

    try:
        results = await asyncio.gather(attempt(), attempt())
    finally:
        await engine.dispose()

    assert sum(isinstance(r, SignalNotExecutableError) for r in results) == 1
    assert sum(not isinstance(r, SignalNotExecutableError) for r in results) == 1
    [(order, _)] = await orders_repo.list_open_orders(db_session)
    assert order.signal_id == sid


async def test_refresh_devuelve_contadores_y_es_idempotente(db_session: AsyncSession) -> None:
    instrument_id, _ = await _new_order(db_session)
    await ohlcv_repo.upsert_candles(
        db_session,
        instrument_id,
        [
            _candle(T0, "1.1", "1.102", "1.099", "1.1"),
            _candle(T0 + H, "1.1", "1.101", "1.079", "1.08"),
        ],
    )
    await db_session.commit()

    first = await refresh_orders(db_session, T0 + 3 * H)
    second = await refresh_orders(db_session, T0 + 3 * H)

    assert (first.orders_checked, first.orders_filled, first.orders_closed) == (1, 1, 1)
    assert (second.orders_checked, second.orders_filled, second.orders_closed) == (0, 0, 0)


async def test_blotter_valora_con_ultimo_cierre(db_session: AsyncSession) -> None:
    instrument_id, _ = await _new_order(db_session)  # SHORT, fill esperado 1.1, units 10
    await ohlcv_repo.upsert_candles(
        db_session, instrument_id, [_candle(T0, "1.1", "1.102", "1.089", "1.09")]
    )
    await db_session.commit()
    await refresh_orders(db_session, T0 + H)
    await db_session.commit()

    blotter = await get_blotter(db_session, SETTINGS, None, 100, T0 + H)

    [order] = blotter.orders
    assert order.status is OrderStatus.OPEN
    assert order.mark_price == Decimal("1.09")
    assert order.unrealized_pnl == Decimal("0.10") and order.pnl == order.unrealized_pnl
    assert order.r_multiple == Decimal("0.001")
    assert blotter.unrealized_pnl_total == Decimal("0.10")
    assert blotter.open_risk == Decimal(100)
    assert blotter.equity == Decimal(10000) and blotter.realized_pnl_total == 0
    assert blotter.daily_loss_limit_reached is False


async def test_blotter_limite_diario_y_filtro_de_estado(db_session: AsyncSession) -> None:
    await _closed_loss(db_session, "-300", T0 - H)
    await _open_order(db_session)

    todas = await get_blotter(db_session, SETTINGS, None, 100, T0)
    abiertas = await get_blotter(db_session, SETTINGS, OrderStatus.PENDING_FILL, 100, T0)
    de_nuevo = await get_blotter(db_session, SETTINGS, None, 100, T0)

    assert todas.daily_loss_limit_reached is True
    assert todas.realized_pnl_today == Decimal(-300) and todas.equity == Decimal(9700)
    assert todas.day_start_equity == Decimal(10000)
    assert len(todas.orders) == 2 and len(abiertas.orders) == 1
    assert abiertas.open_risk == Decimal(100)  # el filtro no recorta el riesgo abierto
    assert de_nuevo == todas  # solo lectura


async def test_journal_coincide_con_build_journal(db_session: AsyncSession) -> None:
    sid = await _approved(db_session)
    rejected = await _approved(db_session, status=SignalStatus.REJECTED)
    await execute_signal(db_session, SETTINGS, sid, T0)
    await db_session.commit()

    journal = await get_journal(db_session, None, 100)

    rows: list[JournalInput] = []
    for entry in journal.entries:
        order = await orders_repo.get_by_signal(db_session, entry.signal_id)
        rows.append(
            JournalInput(
                signal_id=entry.signal_id,
                analysis_id=entry.analysis_id,
                created_at=entry.created_at,
                symbol=entry.symbol,
                timeframe=entry.timeframe,
                direction=entry.direction,
                signal_status=entry.signal_status,
                regime=entry.regime,
                entry=entry.entry,
                stop_loss=entry.stop_loss,
                take_profit=entry.take_profit,
                rr=entry.rr,
                veto_reasons=tuple(entry.veto_reasons),
                rationale=entry.rationale,
                risk_amount=entry.risk_amount,
                order=(
                    JournalOrderInput(
                        order_id=order.id,
                        status=OrderStatus(order.status),
                        risk_amount=order.risk_amount,
                    )
                    if order is not None
                    else None
                ),
            )
        )
    assert journal == build_journal(rows)
    assert {e.signal_id for e in journal.entries} == {sid, rejected}
    assert journal.summary.n_executed == 1 and journal.summary.n_signals == 2


async def test_journal_filtra_por_simbolo_y_rechaza_desconocido(db_session: AsyncSession) -> None:
    await _approved(db_session)
    await _approved(db_session, symbol="BTC/USDT")

    solo_eur = await get_journal(db_session, "EUR/USD", 100)

    assert [e.symbol for e in solo_eur.entries] == ["EUR/USD"]
    with pytest.raises(InstrumentNotFoundError, match="Instrumento desconocido: XYZ"):
        await get_journal(db_session, "XYZ", 100)
