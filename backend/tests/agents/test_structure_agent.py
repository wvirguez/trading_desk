"""Tests del `structure_agent` con `FunctionModel` guionizado (sin red)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import polars as pl
import pytest
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents.deps import AgentDeps
from app.agents.prompts import PROMPT_VERSION, STRUCTURE_PROMPT
from app.agents.runner import run_agent
from app.agents.structure import structure_agent
from app.core.config import Settings
from app.quant.structure import analyze_structure
from app.schemas.enums import Bias, Timeframe
from app.schemas.risk import PortfolioState
from tests.quant._proposal_helpers import SEED

SYMBOL = "EUR/USD"
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _frame(seed: int, n: int = 400, step_hours: int = 1) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    close = 1.10 + np.cumsum(rng.normal(0, 0.003, n))
    open_ = np.concatenate([[1.10], close[:-1]]) + rng.normal(0, 0.002, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.001, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.001, n))
    return pl.DataFrame(
        {
            "ts": [T0 + timedelta(hours=step_hours * i) for i in range(n)],
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 100.0),
        },
        schema={
            "ts": pl.Datetime("us", "UTC"),
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
        },
    )


def _deps() -> AgentDeps:
    return AgentDeps(
        instrument=SEED[SYMBOL],
        candles={Timeframe.H1: _frame(1), Timeframe.H4: _frame(2, step_hours=4)},
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        portfolio=PortfolioState(
            equity=Decimal(10000),
            day_start_equity=Decimal(10000),
            realized_pnl_today=Decimal(0),
            open_positions=[],
        ),
    )


DEPS = _deps()
H1 = analyze_structure(DEPS.candles[Timeframe.H1])
H4 = analyze_structure(DEPS.candles[Timeframe.H4])
OPEN_H1 = [f for f in H1.fvgs if f.mitigated_at is None][-1]
OPEN_H4 = [f for f in H4.fvgs if f.mitigated_at is None][-1]


def _tf(tf: Timeframe, **over: Any) -> dict[str, Any]:
    res = H1 if tf is Timeframe.H1 else H4
    base: dict[str, Any] = {
        "timeframe": tf.value,
        "bias": "BULLISH",
        "last_event": None,
        "key_levels": [str(res.swings[-1].price)],
        "open_fvg_ts": [(OPEN_H1 if tf is Timeframe.H1 else OPEN_H4).ts.isoformat()],
        "comment": "Lectura de prueba.",
    }
    base.update(over)
    return base


def _report(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "symbol": SYMBOL,
        "entry_timeframe": "1h",
        "timeframes": [_tf(Timeframe.H1), _tf(Timeframe.H4)],
        "htf_alignment": "BULLISH",
        "zone_ts": OPEN_H1.ts.isoformat(),
        "invalidation_level": str(H1.swings[-1].price),
        "reasoning": "Alineación alcista.",
    }
    base.update(over)
    return base


def _sequence(reports: list[dict[str, Any]]) -> tuple[FunctionModel, list[int]]:
    """Modelo que devuelve cada informe en orden (el último se repite)."""
    calls = [0]

    def respond(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        rep = reports[min(calls[0], len(reports) - 1)]
        calls[0] += 1
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, rep)])

    return FunctionModel(respond), calls


async def _run(model: FunctionModel) -> Any:
    with structure_agent.override(model=model):
        return await structure_agent.run("Analiza EUR/USD", deps=DEPS)


def _returns(messages: list[ModelMessage], tool: str) -> list[Any]:
    return [
        p.content
        for m in messages
        if isinstance(m, ModelRequest)
        for p in m.parts
        if isinstance(p, ToolReturnPart) and p.tool_name == tool
    ]


async def test_tools_return_exactly_analyze_structure_per_timeframe() -> None:
    seen: dict[str, list[ModelMessage]] = {}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not _returns(messages, "get_structure"):
            return ModelResponse(
                parts=[
                    ToolCallPart("get_structure", {"timeframe": "1h"}),
                    ToolCallPart("get_structure", {"timeframe": "4h"}),
                    ToolCallPart("get_last_close", {"timeframe": "1h"}),
                ]
            )
        seen["m"] = messages
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, _report())])

    await _run(FunctionModel(respond))
    got = _returns(seen["m"], "get_structure")
    assert got == [H1.model_dump(mode="json"), H4.model_dump(mode="json")]
    (last,) = _returns(seen["m"], "get_last_close")
    df = DEPS.candles[Timeframe.H1]
    assert Decimal(last["close"]) == Decimal(repr(df["close"][-1]))
    assert last["timeframe"] == "1h"


async def test_valid_report_passes() -> None:
    model, calls = _sequence([_report()])
    result = await _run(model)
    assert calls[0] == 1
    assert result.output.symbol == SYMBOL
    assert result.output.zone_ts == OPEN_H1.ts


@pytest.mark.parametrize(
    "bad",
    [
        {"timeframes": [_tf(Timeframe.H1, key_levels=["9.99999"]), _tf(Timeframe.H4)]},
        {
            "timeframes": [
                _tf(Timeframe.H1, open_fvg_ts=["2020-01-01T00:00:00+00:00"]),
                _tf(Timeframe.H4),
            ]
        },
        {"invalidation_level": "9.99999"},
        {"zone_ts": "2020-01-01T00:00:00+00:00"},
    ],
    ids=["nivel", "fvg", "invalidacion", "zona"],
)
async def test_invented_figures_are_rejected_then_corrected(bad: dict[str, Any]) -> None:
    model, calls = _sequence([_report(**bad), _report()])
    result = await _run(model)
    assert calls[0] == 2
    retries = [
        p
        for m in result.all_messages()
        if isinstance(m, ModelRequest)
        for p in m.parts
        if isinstance(p, ToolReturnPart) and p.outcome == "retried"
    ]
    assert len(retries) == 1
    assert isinstance(retries[0].content, str)


def _swing_prices(res: Any) -> set[Decimal]:
    return {s.price for s in res.swings}


def test_los_datos_permiten_los_casos_de_invalidacion_y_eventos() -> None:
    assert H1.events and H4.events
    assert OPEN_H1.low not in _swing_prices(H1) and OPEN_H1.high not in _swing_prices(H1)
    only_h4 = _swing_prices(H4) - _swing_prices(H1)
    assert only_h4


@pytest.mark.parametrize(
    "bad",
    [
        {"invalidation_level": str(OPEN_H1.low)},  # borde de FVG del marco de entrada
        {"invalidation_level": str(max(_swing_prices(H4) - _swing_prices(H1)))},  # swing de 4h
    ],
    ids=["borde-fvg", "swing-de-otro-marco"],
)
async def test_invalidation_must_be_entry_timeframe_swing(bad: dict[str, Any]) -> None:
    model, calls = _sequence([_report(**bad), _report()])
    result = await _run(model)
    assert calls[0] == 2
    assert result.output.invalidation_level == H1.swings[-1].price


async def test_invalidation_accepts_any_entry_swing_and_none() -> None:
    older = H1.swings[0].price
    model, calls = _sequence([_report(invalidation_level=str(older))])
    result = await _run(model)
    assert calls[0] == 1 and result.output.invalidation_level == older
    model, calls = _sequence([_report(invalidation_level=None)])
    assert (await _run(model)).output.invalidation_level is None


async def test_last_event_correct_is_accepted() -> None:
    h1 = _tf(Timeframe.H1, last_event=H1.events[-1].type.value)
    h4 = _tf(Timeframe.H4, last_event=H4.events[-1].type.value)
    model, calls = _sequence([_report(timeframes=[h1, h4])])
    result = await _run(model)
    assert calls[0] == 1
    assert result.output.timeframes[0].last_event is H1.events[-1].type


async def test_last_event_wrong_is_rejected_then_corrected() -> None:
    other = "CHOCH" if H1.events[-1].type.value == "BOS" else "BOS"
    wrong = _report(timeframes=[_tf(Timeframe.H1, last_event=other), _tf(Timeframe.H4)])
    model, calls = _sequence([wrong, _report()])
    result = await _run(model)
    assert calls[0] == 2
    retry = next(
        p
        for m in result.all_messages()
        if isinstance(m, ModelRequest)
        for p in m.parts
        if isinstance(p, ToolReturnPart) and p.outcome == "retried"
    )
    assert "last_event" in str(retry.content)


async def test_htf_alignment_contradicting_higher_timeframe_is_rejected() -> None:
    bearish_h4 = [_tf(Timeframe.H1), _tf(Timeframe.H4, bias="BEARISH")]
    model, calls = _sequence([_report(timeframes=bearish_h4), _report(htf_alignment="NEUTRAL")])
    result = await _run(model)
    assert calls[0] == 2
    assert result.output.htf_alignment is Bias.NEUTRAL


async def test_htf_alignment_rule_is_conservative() -> None:
    # NEUTRAL siempre; marcos superiores NEUTRAL o solo inferiores/propio no contradicen.
    cases = [
        _report(htf_alignment="NEUTRAL", timeframes=[_tf(Timeframe.H1), _tf(Timeframe.H4)]),
        _report(timeframes=[_tf(Timeframe.H1), _tf(Timeframe.H4, bias="NEUTRAL")]),
        _report(
            htf_alignment="BEARISH",
            timeframes=[_tf(Timeframe.H1, bias="BULLISH"), _tf(Timeframe.H4, bias="BEARISH")],
        ),
    ]
    for rep in cases:
        model, calls = _sequence([rep])
        await _run(model)
        assert calls[0] == 1


async def test_invented_level_always_fails() -> None:
    bad = _report(invalidation_level="9.99999")
    model, calls = _sequence([bad])
    with pytest.raises(UnexpectedModelBehavior):
        await _run(model)
    assert calls[0] == 3


async def test_zone_must_not_be_mitigated() -> None:
    mitigated = [f for f in H1.fvgs if f.mitigated_at is not None]
    assert mitigated, "los datos sintéticos deben contener FVG mitigados"
    model, _ = _sequence([_report(zone_ts=mitigated[0].ts.isoformat()), _report()])
    result = await _run(model)
    assert result.output.zone_ts == OPEN_H1.ts


async def test_less_than_two_timeframes_fails() -> None:
    model, calls = _sequence([_report(timeframes=[_tf(Timeframe.H1)])])
    with pytest.raises(UnexpectedModelBehavior):
        await _run(model)
    assert calls[0] == 3


async def test_unrequested_timeframes_fail() -> None:
    d1 = _tf(Timeframe.H1, timeframe="1d")
    model, calls = _sequence([_report(timeframes=[_tf(Timeframe.H1), d1])])
    with pytest.raises(UnexpectedModelBehavior):
        await _run(model)
    assert calls[0] == 3


async def test_symbol_and_entry_timeframe_must_match_deps() -> None:
    model, calls = _sequence([_report(symbol="BTC/USDT"), _report(entry_timeframe="1d"), _report()])
    await _run(model)
    assert calls[0] == 3


async def test_trace_contains_prompt_version_and_prompt() -> None:
    model, _ = _sequence([_report()])
    with structure_agent.override(model=model):
        run = await run_agent(
            structure_agent,
            "Analiza EUR/USD",
            DEPS,
            settings=Settings(_env_file=None),  # type: ignore[call-arg]
        )
    assert run.trace["prompt_version"] == PROMPT_VERSION
    assert STRUCTURE_PROMPT in run.trace["system_prompt"]


async def test_unknown_timeframe_tool_call_is_retried() -> None:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("get_structure", {"timeframe": "1d"})])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, _report())])

    result = await _run(FunctionModel(respond))
    assert result.output.htf_alignment is Bias.BULLISH
