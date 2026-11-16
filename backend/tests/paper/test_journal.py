"""Tests puros de `build_journal` (D142, D143): valores calculados a mano."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper.journal import JournalInput, JournalOrderInput, build_journal
from app.schemas.enums import (
    Direction,
    JournalOutcome,
    OrderStatus,
    RegimeLabel,
    SignalStatus,
    Timeframe,
)

T0 = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)


def _row(
    n: int,
    status: SignalStatus = SignalStatus.EXECUTED,
    *,
    rr: str = "2",
    order: OrderStatus | None = None,
    pnl: str | None = None,
    risk: str = "100",
) -> JournalInput:
    closed = order in (OrderStatus.CLOSED_TP, OrderStatus.CLOSED_SL)
    return JournalInput(
        signal_id=uuid.UUID(int=n),
        analysis_id=uuid.UUID(int=1000 + n),
        created_at=T0 + timedelta(hours=n),
        symbol="EUR/USD",
        timeframe=Timeframe.H1,
        direction=Direction.LONG,
        signal_status=status,
        regime=RegimeLabel.TRENDING,
        entry=Decimal("1.1"),
        stop_loss=Decimal("1.09"),
        take_profit=Decimal("1.12"),
        rr=Decimal(rr),
        veto_reasons=(),
        rationale="x",
        risk_amount=Decimal(risk),
        order=None
        if order is None
        else JournalOrderInput(
            order_id=uuid.UUID(int=2000 + n),
            status=order,
            risk_amount=Decimal(risk),
            fill_price=None if order is OrderStatus.PENDING_FILL else Decimal("1.1"),
            exit_price=Decimal("1.12") if closed else None,
            realized_pnl=Decimal(pnl) if closed and pnl is not None else None,
            closed_at=T0 + timedelta(hours=n + 1) if closed else None,
        ),
    )


def test_metricas_calculadas_a_mano() -> None:
    rows = [
        _row(1, rr="2", order=OrderStatus.CLOSED_TP, pnl="200"),  # R = +2
        _row(2, rr="3", order=OrderStatus.CLOSED_SL, pnl="-100"),  # R = -1
        _row(3, rr="1", order=OrderStatus.CLOSED_SL, pnl="-50", risk="100"),  # R = -0.5
        _row(4, rr="2", order=OrderStatus.OPEN),
        _row(5, SignalStatus.APPROVED, rr="2"),
        _row(6, SignalStatus.REJECTED, rr="9"),
    ]

    s = build_journal(rows).summary

    assert (s.n_signals, s.n_approved, s.n_rejected, s.n_executed) == (6, 5, 1, 4)
    assert (s.n_closed, s.n_wins, s.n_losses) == (3, 1, 2)
    assert s.win_rate == pytest.approx(1 / 3)
    assert s.total_pnl == Decimal(50)
    # R: (2 - 1 - 0.5) / 3
    assert s.expectancy_r == pytest.approx(0.5 / 3)
    assert s.avg_r_realized == s.expectancy_r
    # rr de APPROVED+EXECUTED: (2 + 3 + 1 + 2 + 2) / 5 = 2 (la REJECTED con 9 no cuenta)
    assert s.avg_rr_emitted == pytest.approx(2.0)


def test_sin_cerradas_las_metricas_son_none() -> None:
    journal = build_journal(
        [_row(1, order=OrderStatus.OPEN), _row(2, SignalStatus.REJECTED, rr="1")]
    )
    s = journal.summary

    assert s.n_closed == 0 and s.total_pnl == 0
    assert s.win_rate is None and s.expectancy_r is None and s.avg_r_realized is None
    assert s.avg_rr_emitted == pytest.approx(2.0)
    assert len(s.warnings) == 1 and "Sin operaciones cerradas" in s.warnings[0]


def test_sin_senales_todo_es_none_o_cero() -> None:
    s = build_journal([]).summary

    assert s.n_signals == 0 and s.avg_rr_emitted is None and s.win_rate is None


def test_aviso_de_muestra_pequena_solo_por_debajo_de_30() -> None:
    def closed(n: int) -> list[JournalInput]:
        return [_row(i, order=OrderStatus.CLOSED_TP, pnl="100") for i in range(1, n + 1)]

    small = build_journal(closed(29)).summary
    enough = build_journal(closed(30)).summary

    assert small.warnings == [
        "Muestra pequeña: 29 operaciones cerradas (< 30); las métricas no son concluyentes."
    ]
    assert enough.warnings == []
    assert enough.n_closed == 30 and enough.win_rate == 1.0


@pytest.mark.parametrize(
    ("status", "order", "expected"),
    [
        (SignalStatus.EXECUTED, OrderStatus.CLOSED_TP, JournalOutcome.WIN),
        (SignalStatus.EXECUTED, OrderStatus.CLOSED_SL, JournalOutcome.LOSS),
        (SignalStatus.EXECUTED, OrderStatus.PENDING_FILL, JournalOutcome.PENDING_FILL),
        (SignalStatus.EXECUTED, OrderStatus.OPEN, JournalOutcome.OPEN),
        (SignalStatus.REJECTED, None, JournalOutcome.NOT_EXECUTED),
        (SignalStatus.APPROVED, None, JournalOutcome.NOT_EXECUTED),
    ],
)
def test_outcome_segun_la_orden(
    status: SignalStatus, order: OrderStatus | None, expected: JournalOutcome
) -> None:
    pnl = "100" if order is OrderStatus.CLOSED_TP else "-100"
    entry = build_journal([_row(1, status, order=order, pnl=pnl)]).entries[0]

    assert entry.outcome is expected
    assert (entry.order_id is None) == (order is None)


def test_r_multiple_es_pnl_entre_riesgo_de_la_orden() -> None:
    entry = build_journal([_row(1, order=OrderStatus.CLOSED_SL, pnl="-75", risk="150")]).entries[0]

    assert entry.r_multiple == Decimal("-0.5")
    assert build_journal([_row(2, order=OrderStatus.OPEN)]).entries[0].r_multiple is None


def test_entradas_recientes_primero_y_determinismo() -> None:
    rows = [_row(1), _row(3, SignalStatus.REJECTED), _row(2, SignalStatus.APPROVED)]

    first = build_journal(rows)
    second = build_journal(list(reversed(rows)))

    assert [e.signal_id.int for e in first.entries] == [3, 2, 1]
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
