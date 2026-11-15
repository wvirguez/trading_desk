"""Tests de ejemplo de la propuesta determinista (D93) con niveles construidos a mano."""

from decimal import Decimal

import pytest

from app.quant.proposal import NoTradeReason, ProposalParams, build_proposal
from app.schemas.enums import Bias, Direction, Playbook
from app.schemas.signals import ProposedSignal
from tests.quant._proposal_helpers import SEED, make_fvg, make_quant, make_structure

D = Decimal
PARAMS = ProposalParams(target_rr=D("2.0"), sl_atr_buffer=D("0.5"))
EUR = SEED["EUR/USD"]


def _ok(r: ProposedSignal | NoTradeReason) -> ProposedSignal:
    assert isinstance(r, ProposedSignal), r
    return r


def test_long_con_fvg_entra_en_el_borde_de_la_zona() -> None:
    r = _ok(
        build_proposal(
            make_structure(invalidation=D("1.07000")),
            make_quant(),
            D("1.08500"),
            D("0.00200"),
            EUR,
            PARAMS,
            fvgs=[make_fvg(Direction.LONG, "1.07800", "1.08000")],
        )
    )
    assert r.direction is Direction.LONG
    assert r.entry == D("1.08000")  # borde cercano (alto) de la zona alcista
    assert r.stop_loss == D("1.06900")  # 1.07000 - 0.5 * 0.002
    assert r.take_profit == D("1.10200")  # entrada + 2 * 0.0110
    assert r.rr == D("2")
    assert r.symbol == "EUR/USD"
    assert "FVG" in r.source


def test_sin_zona_entra_en_el_ultimo_cierre() -> None:
    r = _ok(
        build_proposal(
            make_structure(zone_ts=None), make_quant(), D("1.08500"), D("0.00200"), EUR, PARAMS
        )
    )
    assert r.entry == D("1.08500")
    assert "último cierre" in r.source


def test_zona_mitigada_o_inexistente_o_de_otro_sentido_se_ignora() -> None:
    for fvgs in (
        [make_fvg(Direction.LONG, "1.07800", "1.08000", mitigated=True)],
        [make_fvg(Direction.SHORT, "1.07800", "1.08000")],
        [],
    ):
        r = _ok(
            build_proposal(
                make_structure(), make_quant(), D("1.08500"), D("0.00200"), EUR, PARAMS, fvgs=fvgs
            )
        )
        assert r.entry == D("1.08500")


def test_short_con_fvg_bajista() -> None:
    r = _ok(
        build_proposal(
            make_structure(bias=Bias.BEARISH, invalidation=D("1.09000")),
            make_quant(),
            D("1.08000"),
            D("0.00200"),
            EUR,
            PARAMS,
            fvgs=[make_fvg(Direction.SHORT, "1.08300", "1.08500")],
        )
    )
    assert r.direction is Direction.SHORT
    assert r.entry == D("1.08300")  # borde cercano (bajo) de la zona bajista
    assert r.stop_loss == D("1.09100")
    assert r.take_profit == D("1.06700")


def test_sl_se_redondea_en_contra_de_la_operacion() -> None:
    # Colchón 0.5 * 0.00003 = 0.000015 -> LONG: 1.07000 - 0.000015 = 1.069985 -> baja a 1.06998
    long = _ok(
        build_proposal(make_structure(), make_quant(), D("1.08000"), D("0.00003"), EUR, PARAMS)
    )
    assert long.stop_loss == D("1.06998")
    # SHORT: 1.09000 + 0.000015 = 1.090015 -> sube a 1.09002
    short = _ok(
        build_proposal(
            make_structure(bias=Bias.BEARISH, invalidation=D("1.09000")),
            make_quant(),
            D("1.08000"),
            D("0.00003"),
            EUR,
            PARAMS,
        )
    )
    assert short.stop_loss == D("1.09002")


def test_tp_se_redondea_alejandose_de_la_entrada() -> None:
    inst = SEED["NAS100"]  # tick 0.1
    r = _ok(
        build_proposal(
            make_structure(symbol="NAS100", invalidation=D("19900.0")),
            make_quant(symbol="NAS100"),
            D("20000.0"),
            D("1.0"),
            inst,
            ProposalParams(target_rr=D("2.0"), sl_atr_buffer=D("0.37")),
        )
    )
    # SL = 19900 - 0.37 = 19899.63 -> 19899.6 ; distancia 100.4 ; TP = 20200.8
    assert r.stop_loss == D("19899.6")
    assert r.take_profit == D("20200.8")
    assert r.rr >= D("2.0")


@pytest.mark.parametrize(
    ("symbol", "close", "atr", "inval", "sl", "tp"),
    [
        ("BTC/USDT", "70000.00", "500.00", "68000.00", "67750.00", "74500.00"),
        ("EUR/USD", "1.08500", "0.00200", "1.07000", "1.06900", "1.11700"),
        ("XAU/USD", "2400.000", "10.000", "2350.000", "2345.000", "2510.000"),
        ("NAS100", "20000.0", "40.0", "19800.0", "19780.0", "20440.0"),
    ],
)
def test_cuatro_instrumentos_del_seed(
    symbol: str, close: str, atr: str, inval: str, sl: str, tp: str
) -> None:
    inst = SEED[symbol]
    r = _ok(
        build_proposal(
            make_structure(symbol=symbol, invalidation=D(inval)),
            make_quant(symbol=symbol),
            D(close),
            D(atr),
            inst,
            PARAMS,
        )
    )
    assert (r.entry, r.stop_loss, r.take_profit) == (D(close), D(sl), D(tp))
    for nivel in (r.entry, r.stop_loss, r.take_profit):
        assert nivel % inst.tick_size == 0


def test_mean_reversion_va_contra_la_desviacion() -> None:
    corto = _ok(
        build_proposal(
            make_structure(bias=Bias.NEUTRAL, invalidation=D("1.09000")),
            make_quant(playbook=Playbook.MEAN_REVERSION, zscore=2.3),
            D("1.08000"),
            D("0.00200"),
            EUR,
            PARAMS,
        )
    )
    assert corto.direction is Direction.SHORT
    largo = _ok(
        build_proposal(
            make_structure(bias=Bias.BULLISH),
            make_quant(playbook=Playbook.MEAN_REVERSION, zscore=-2.3),
            D("1.08000"),
            D("0.00200"),
            EUR,
            PARAMS,
        )
    )
    assert largo.direction is Direction.LONG


def _motivo(r: ProposedSignal | NoTradeReason) -> str:
    assert isinstance(r, NoTradeReason), r
    assert r.reason
    return r.reason


def test_sin_propuesta_con_motivo() -> None:
    args = (D("1.08500"), D("0.00200"), EUR, PARAMS)
    assert "NO_TRADE" in _motivo(
        build_proposal(make_structure(), make_quant(playbook=Playbook.NO_TRADE), *args)
    )
    assert (
        "neutral"
        in _motivo(build_proposal(make_structure(bias=Bias.NEUTRAL), make_quant(), *args)).lower()
    )
    # MEAN_REVERSION contra el sesgo HTF: z>0 -> SHORT pero el sesgo es alcista.
    assert "incompatible" in _motivo(
        build_proposal(
            make_structure(bias=Bias.BULLISH),
            make_quant(playbook=Playbook.MEAN_REVERSION, zscore=2.0),
            *args,
        )
    )
    assert "z-score" in _motivo(
        build_proposal(
            make_structure(), make_quant(playbook=Playbook.MEAN_REVERSION, zscore=0.0), *args
        )
    )


def test_sin_invalidacion_o_invalidacion_del_lado_equivocado() -> None:
    args = (D("1.08500"), D("0.00200"), EUR, PARAMS)
    assert "invalidación" in _motivo(
        build_proposal(make_structure(invalidation=None), make_quant(), *args)
    )
    # LONG con invalidación por encima de la entrada.
    assert "invalidación" in _motivo(
        build_proposal(make_structure(invalidation=D("1.09000")), make_quant(), *args)
    )


def test_atr_cero_y_sl_no_positivo_sin_propuesta() -> None:
    assert "ATR" in _motivo(
        build_proposal(make_structure(), make_quant(), D("1.085"), D("0"), EUR, PARAMS)
    )
    assert "positivo" in _motivo(
        build_proposal(
            make_structure(invalidation=D("0.00100")),
            make_quant(),
            D("1.085"),
            D("0.00200"),
            EUR,
            PARAMS,
        )
    )


def test_entradas_incoherentes_lanzan_value_error() -> None:
    with pytest.raises(ValueError, match="símbolo"):
        build_proposal(
            make_structure(symbol="BTC/USDT"), make_quant(), D("1.085"), D("0.002"), EUR, PARAMS
        )
    with pytest.raises(ValueError, match="último cierre"):
        build_proposal(make_structure(), make_quant(), D("-1"), D("0.002"), EUR, PARAMS)
    with pytest.raises(ValueError, match="target_rr"):
        ProposalParams(target_rr=D("0"), sl_atr_buffer=D("0.5"))
