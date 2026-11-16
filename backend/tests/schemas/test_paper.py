import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.enums import Direction, OrderStatus, Timeframe
from app.schemas.paper import (
    BlotterSchema,
    OrderReceiptSchema,
    PaperOrderSchema,
    PaperRefreshResult,
)

D = Decimal
T0 = datetime(2024, 1, 1, 10, tzinfo=UTC)
T1 = datetime(2024, 1, 1, 11, tzinfo=UTC)
T2 = datetime(2024, 1, 1, 12, tzinfo=UTC)

CLOSED_SL = {
    "status": OrderStatus.CLOSED_SL,
    "fill_price": D("60000"),
    "filled_at": T1,
    "exit_price": D("59800"),
    "closed_at": T2,
    "realized_pnl": D("-100"),
    "pnl": D("-100"),
    "r_multiple": D("-1"),
}
OPEN = {
    "status": OrderStatus.OPEN,
    "fill_price": D("60000"),
    "filled_at": T1,
    "mark_price": D("60100"),
    "unrealized_pnl": D("50"),
    "pnl": D("50"),
    "r_multiple": D("0.5"),
}


def _base(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "order_id": uuid4(),
        "signal_id": uuid4(),
        "symbol": "BTCUSDT",
        "timeframe": Timeframe.H1,
        "direction": Direction.LONG,
        "units": D("0.5"),
        "signal_entry": D("60000"),
        "stop_loss": D("59800"),
        "take_profit": D("60400"),
        "risk_amount": D("100"),
        "status": OrderStatus.PENDING_FILL,
        "executed_at": T0,
        "warnings": [],
    }
    data.update(over)
    return data


def _receipt(**over: Any) -> OrderReceiptSchema:
    return OrderReceiptSchema(**_base(**over))


def _order(**over: Any) -> PaperOrderSchema:
    return PaperOrderSchema(**_base(**over))


def _blotter(**over: Any) -> BlotterSchema:
    data: dict[str, Any] = {
        "equity": D("10000"),
        "day_start_equity": D("10000"),
        "realized_pnl_today": D("0"),
        "realized_pnl_total": D("0"),
        "unrealized_pnl_total": D("50"),
        "open_risk": D("100"),
        "daily_loss_limit_reached": False,
        "orders": [_order(**OPEN)],
        "warnings": [],
    }
    data.update(over)
    return BlotterSchema(**data)


# --- recibo ---------------------------------------------------------------------------------


def test_recibo_pending_fill_valido() -> None:
    r = _receipt()
    assert r.simulated is True
    assert r.fill_price is None


def test_recibo_open_y_cerrada_validos() -> None:
    assert _receipt(status=OrderStatus.OPEN, fill_price=D("60000"), filled_at=T1)
    assert _receipt(status=OrderStatus.CLOSED_TP, fill_price=D("60000"), filled_at=T1)


@pytest.mark.parametrize("status", [OrderStatus.OPEN, OrderStatus.CLOSED_TP, OrderStatus.CLOSED_SL])
def test_recibo_con_fill_exige_fill_price_y_filled_at(status: OrderStatus) -> None:
    with pytest.raises(ValidationError, match="requiere fill_price y filled_at"):
        _receipt(status=status)
    with pytest.raises(ValidationError, match="requiere fill_price y filled_at"):
        _receipt(status=status, fill_price=D("60000"))
    with pytest.raises(ValidationError, match="requiere fill_price y filled_at"):
        _receipt(status=status, filled_at=T1)


def test_pending_fill_con_fill_price_falla() -> None:
    with pytest.raises(ValidationError, match="PENDING_FILL no puede tener fill_price"):
        _receipt(fill_price=D("60000"))
    with pytest.raises(ValidationError, match="PENDING_FILL no puede tener fill_price"):
        _receipt(filled_at=T1)


def test_simulated_solo_admite_true() -> None:
    with pytest.raises(ValidationError, match="simulated"):
        _receipt(simulated=False)
    with pytest.raises(ValidationError, match="simulated"):
        _order(simulated=False)


@pytest.mark.parametrize("campo", ["units", "signal_entry", "risk_amount", "stop_loss"])
def test_recibo_rechaza_importes_no_positivos(campo: str) -> None:
    with pytest.raises(ValidationError, match=f"{campo} debe ser un decimal finito mayor que 0"):
        _receipt(**{campo: D("0")})


# --- orden ----------------------------------------------------------------------------------


def test_orden_pending_open_y_cerrada_validas() -> None:
    assert _order().pnl is None
    assert _order(**OPEN).unrealized_pnl == D("50")
    assert _order(**{**CLOSED_SL}).realized_pnl == D("-100")
    tp = {
        **CLOSED_SL,
        "status": OrderStatus.CLOSED_TP,
        "exit_price": D("60400"),
        "realized_pnl": D("200"),
        "pnl": D("200"),
        "r_multiple": D("2"),
    }
    assert _order(**tp).status is OrderStatus.CLOSED_TP


@pytest.mark.parametrize("falta", ["exit_price", "closed_at", "realized_pnl"])
@pytest.mark.parametrize("status", [OrderStatus.CLOSED_TP, OrderStatus.CLOSED_SL])
def test_cerrada_exige_salida(falta: str, status: OrderStatus) -> None:
    datos = {**CLOSED_SL, "status": status, falta: None}
    with pytest.raises(ValidationError, match=f"requiere .*{falta}"):
        _order(**datos)


def test_orden_open_sin_fill_price_falla() -> None:
    datos = {**OPEN, "fill_price": None}
    with pytest.raises(ValidationError, match="requiere fill_price y filled_at"):
        _order(**datos)


def test_orden_pending_con_fill_price_falla() -> None:
    with pytest.raises(ValidationError, match="PENDING_FILL no puede tener fill_price"):
        _order(fill_price=D("60000"), filled_at=T1)


@pytest.mark.parametrize("estado", [OrderStatus.PENDING_FILL, OrderStatus.OPEN])
def test_realized_pnl_en_orden_no_cerrada_falla(estado: OrderStatus) -> None:
    datos = {**(OPEN if estado is OrderStatus.OPEN else {}), "status": estado}
    with pytest.raises(ValidationError, match="realized_pnl solo existe en órdenes cerradas"):
        _order(**datos, realized_pnl=D("10"))


def test_orden_no_cerrada_sin_salida() -> None:
    with pytest.raises(ValidationError, match="no puede tener exit_price ni closed_at"):
        _order(**OPEN, exit_price=D("60100"))
    with pytest.raises(ValidationError, match="no puede tener exit_price ni closed_at"):
        _order(**OPEN, closed_at=T2)


def test_mark_y_unrealized_solo_en_open() -> None:
    with pytest.raises(ValidationError, match="solo existen en órdenes OPEN"):
        _order(mark_price=D("1"))
    with pytest.raises(ValidationError, match="solo existen en órdenes OPEN"):
        _order(**{**CLOSED_SL, "unrealized_pnl": D("1")})


def test_pnl_coherente_con_el_estado() -> None:
    with pytest.raises(ValidationError, match="pnl debe ser None"):
        _order(pnl=D("1"))
    with pytest.raises(ValidationError, match="igual a unrealized_pnl"):
        _order(**{**OPEN, "pnl": D("999")})
    with pytest.raises(ValidationError, match="igual a realized_pnl"):
        _order(**{**CLOSED_SL, "pnl": D("1")})
    with pytest.raises(ValidationError, match="r_multiple requiere pnl"):
        _order(r_multiple=D("1"))


# --- blotter y refresh ----------------------------------------------------------------------


def test_blotter_valido_y_vacio() -> None:
    assert len(_blotter().orders) == 1
    b = _blotter(orders=[], open_risk=D("0"), unrealized_pnl_total=D("0"))
    assert b.orders == []


def test_blotter_open_risk_negativo_falla() -> None:
    with pytest.raises(ValidationError, match="open_risk debe ser un decimal finito >= 0"):
        _blotter(open_risk=D("-1"))


def test_refresh_valido_y_contadores_negativos() -> None:
    r = PaperRefreshResult(orders_checked=3, orders_filled=1, orders_closed=1, warnings=[])
    assert r.orders_checked == 3
    with pytest.raises(ValidationError, match="orders_closed no puede ser negativo"):
        PaperRefreshResult(orders_checked=0, orders_filled=0, orders_closed=-1, warnings=[])


# --- JSON, extra, inmutabilidad -------------------------------------------------------------


def test_precios_y_pnl_viajan_como_cadena_y_ida_y_vuelta() -> None:
    o = _order(**CLOSED_SL)
    payload = json.loads(o.model_dump_json())
    for campo in ("units", "signal_entry", "fill_price", "exit_price", "realized_pnl", "pnl"):
        assert isinstance(payload[campo], str), campo
    assert payload["realized_pnl"] == "-100"
    assert payload["simulated"] is True
    assert PaperOrderSchema.model_validate_json(o.model_dump_json()) == o

    b = _blotter()
    bp = json.loads(b.model_dump_json())
    assert bp["equity"] == "10000"
    assert bp["open_risk"] == "100"
    assert bp["orders"][0]["unrealized_pnl"] == "50"
    assert BlotterSchema.model_validate_json(b.model_dump_json()) == b

    r = _receipt(status=OrderStatus.OPEN, fill_price=D("60000"), filled_at=T1)
    assert json.loads(r.model_dump_json())["fill_price"] == "60000"
    assert OrderReceiptSchema.model_validate_json(r.model_dump_json()) == r


def test_extra_forbid() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        _receipt(campo_inventado=1)
    with pytest.raises(ValidationError, match="Extra inputs"):
        _order(campo_inventado=1)
    with pytest.raises(ValidationError, match="Extra inputs"):
        _blotter(campo_inventado=1)
    with pytest.raises(ValidationError, match="Extra inputs"):
        PaperRefreshResult(
            orders_checked=0, orders_filled=0, orders_closed=0, warnings=[], campo_inventado=1
        )  # type: ignore[call-arg]


def test_inmutabilidad() -> None:
    with pytest.raises(ValidationError, match="frozen"):
        _receipt().status = OrderStatus.OPEN  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        _order().pnl = D("1")  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        _blotter().equity = D("1")  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        PaperRefreshResult(
            orders_checked=0, orders_filled=0, orders_closed=0, warnings=[]
        ).orders_checked = 1  # type: ignore[misc]
