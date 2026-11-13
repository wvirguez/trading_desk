"""Position sizing con tick y lote reales del seed (D60)."""

from decimal import Decimal

import pytest

from app.risk.sizing import position_size
from app.schemas.enums import AssetClass, Provider, SessionType
from app.schemas.instrument import InstrumentSchema


def _inst(symbol: str, tick: str, lot: str, ac: AssetClass = AssetClass.FX) -> InstrumentSchema:
    return InstrumentSchema(
        symbol=symbol,
        asset_class=ac,
        provider=Provider.YAHOO,
        provider_symbol=symbol,
        base_currency=symbol[:3],
        quote_currency="USD",
        tick_size=Decimal(tick),
        lot_size=Decimal(lot),
        session=SessionType.FX_24_5,
    )


EURUSD = _inst("EUR/USD", "0.00001", "1")
BTC = _inst("BTC/USDT", "0.01", "0.00001", AssetClass.CRYPTO)
XAU = _inst("XAU/USD", "0.001", "1", AssetClass.METAL)
NAS = _inst("NAS100", "0.1", "0.1", AssetClass.INDEX)
D = Decimal


def test_eurusd_ejemplo() -> None:
    # riesgo = 10000 * 1 / 100 = 100; distancia = 0.00200; units = 100 / 0.002 = 50000
    r = position_size(D(10000), D("1.0"), D("1.08500"), D("1.08300"), EURUSD)
    assert r.stop_distance == D("0.00200")
    assert r.units == D(50000)
    assert r.risk_amount == D(100)
    assert r.risk_pct == D(1)
    assert r.notional == D(50000) * D("1.08500")


def test_corto_usa_valor_absoluto() -> None:
    largo = position_size(D(10000), D(1), D("1.08500"), D("1.08300"), EURUSD)
    corto = position_size(D(10000), D(1), D("1.08300"), D("1.08500"), EURUSD)
    assert largo.units == corto.units
    assert largo.stop_distance == corto.stop_distance


def test_btc_lote_fraccionario() -> None:
    # riesgo 100; distancia 500 -> 0.2 BTC (lote 0.00001)
    r = position_size(D(10000), D(1), D(60000), D(59500), BTC)
    assert r.units == D("0.2")
    assert r.risk_amount == D(100)
    # distancia 300 -> 0.33333.. -> baja a 0.33333
    r2 = position_size(D(10000), D(1), D(60000), D(59700), BTC)
    assert r2.units == D("0.33333")
    assert r2.risk_amount == D("99.999")
    assert r2.risk_pct < D(1)


def test_xauusd_lote_entero() -> None:
    # riesgo 100; distancia 10.000 -> 10 unidades (lote 1)
    r = position_size(D(10000), D(1), D("2400.000"), D("2390.000"), XAU)
    assert r.units == D(10)
    assert r.risk_amount == D(100)
    # distancia 30.000 -> 3.33 -> baja a 3 unidades; riesgo real 90
    r2 = position_size(D(10000), D(1), D("2400.000"), D("2370.000"), XAU)
    assert r2.units == D(3)
    assert r2.risk_amount == D(90)


def test_nas100_lote_decimal() -> None:
    # riesgo 100; distancia 50.0 -> 2.0 unidades (lote 0.1)
    r = position_size(D(10000), D(1), D("20000.0"), D("19950.0"), NAS)
    assert r.units == D("2.0")
    assert r.risk_amount == D(100)
    # distancia 30.0 -> 3.33 -> baja a 3.3 unidades; riesgo real 99.0
    r2 = position_size(D(10000), D(1), D("20000.0"), D("19970.0"), NAS)
    assert r2.units == D("3.3")
    assert r2.risk_amount == D("99.0")


def test_distancia_se_redondea_hacia_arriba_al_tick() -> None:
    r = position_size(D(10000), D(1), D("100.004"), D("99.000"), BTC)
    assert r.stop_distance == D("1.01")


def test_por_debajo_del_lote_da_cero() -> None:
    r = position_size(D(100), D("0.1"), D(60000), D(30000), BTC)
    assert r.units == 0
    assert r.risk_amount == 0
    assert r.notional == 0


@pytest.mark.parametrize(
    ("equity", "risk", "entry", "stop"),
    [
        (D(0), D(1), D(2), D(1)),
        (D(-5), D(1), D(2), D(1)),
        (D(100), D(0), D(2), D(1)),
        (D(100), D(-1), D(2), D(1)),
        (D(100), D(1), D(0), D(1)),
        (D(100), D(1), D(2), D(0)),
        (D(100), D(1), D(-2), D(1)),
        (D(100), D(1), D(2), D(2)),
    ],
)
def test_entradas_invalidas(equity: Decimal, risk: Decimal, entry: Decimal, stop: Decimal) -> None:
    with pytest.raises(ValueError, match=r"recibido|coinciden"):
        position_size(equity, risk, entry, stop, EURUSD)
