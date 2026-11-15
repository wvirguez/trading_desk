"""Propiedades de la propuesta determinista (D93)."""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.quant.proposal import ProposalParams, build_proposal
from app.schemas.enums import Bias, Direction
from app.schemas.signals import ProposedSignal
from tests.quant._proposal_helpers import SEED, make_fvg, make_quant, make_structure

D = Decimal
prices = st.decimals(D("0.001"), D("100000"), places=5)
atrs = st.decimals(D("0.00001"), D("1000"), places=5)
rrs = st.decimals(D("1.0"), D("5.0"), places=2)
buffers = st.decimals(D("0"), D("2"), places=2)
symbols = st.sampled_from(sorted(SEED))
biases = st.sampled_from([Bias.BULLISH, Bias.BEARISH])


@settings(derandomize=True, max_examples=300, deadline=None)
@given(symbols, biases, prices, prices, atrs, rrs, buffers, st.booleans(), prices)
def test_propiedades(
    symbol: str,
    bias: Bias,
    close: Decimal,
    inval: Decimal,
    atr: Decimal,
    rr: Decimal,
    buf: Decimal,
    con_zona: bool,
    zona: Decimal,
) -> None:
    inst = SEED[symbol]
    tick = inst.tick_size
    fvgs = (
        [
            make_fvg(
                Direction.LONG if bias is Bias.BULLISH else Direction.SHORT,
                str(zona),
                str(zona + atr),
            )
        ]
        if con_zona
        else []
    )
    r = build_proposal(
        make_structure(symbol=symbol, bias=bias, invalidation=inval),
        make_quant(symbol=symbol),
        close,
        atr,
        inst,
        ProposalParams(target_rr=rr, sl_atr_buffer=buf),
        fvgs=fvgs,
    )
    if not isinstance(r, ProposedSignal):
        assert r.reason
        return
    for nivel in (r.entry, r.stop_loss, r.take_profit):
        assert nivel % tick == 0
        assert nivel > 0
    if r.direction is Direction.LONG:
        assert r.stop_loss < r.entry < r.take_profit
        assert r.stop_loss <= inval
    else:
        assert r.take_profit < r.entry < r.stop_loss
        assert r.stop_loss >= inval
    # El TP se redondea alejándose de la entrada: el R:R real nunca baja del objetivo
    # (el rr publicado se trunca a 4 decimales, por eso se compara con el real).
    real = abs(r.take_profit - r.entry) / abs(r.entry - r.stop_loss)
    assert real >= rr
    assert r.rr <= real
    assert r.rr >= rr
