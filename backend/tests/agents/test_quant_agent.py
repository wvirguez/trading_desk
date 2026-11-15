"""Tests del `quant_agent` con `FunctionModel` guionizado (sin red)."""

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
from app.agents.prompts import PROMPT_VERSION, QUANT_PROMPT
from app.agents.quant import quant_agent
from app.agents.runner import run_agent
from app.core.config import Settings
from app.quant.features import atr, log_returns, rolling_volatility
from app.quant.regime import classify_regime
from app.quant.regime_stats import adf_pvalue, hurst_exponent, zscore
from app.risk.kelly import kelly_fraction
from app.schemas.enums import Playbook, RegimeLabel, Timeframe
from app.schemas.risk import PortfolioState
from tests.quant._proposal_helpers import SEED
from tests.quant.synthetic import mean_reverting, trending

SYMBOL = "EUR/USD"
T0 = datetime(2026, 1, 1, tzinfo=UTC)
SETTINGS = Settings(_env_file=None)  # type: ignore[call-arg]


def _frame(close: np.ndarray, step_hours: int = 1) -> pl.DataFrame:
    n = len(close)
    return pl.DataFrame(
        {
            "ts": [T0 + timedelta(hours=step_hours * i) for i in range(n)],
            "open": close,
            "high": close + 0.5,
            "low": close - 0.4,
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
        candles={
            Timeframe.H1: _frame(trending(400, seed=7)),
            Timeframe.H4: _frame(mean_reverting(400, seed=3), step_hours=4),
        },
        settings=SETTINGS,
        portfolio=PortfolioState(
            equity=Decimal(10000),
            day_start_equity=Decimal(10000),
            realized_pnl_today=Decimal(0),
            open_positions=[],
        ),
    )


DEPS = _deps()
H1_DF = DEPS.candles[Timeframe.H1]
H4_DF = DEPS.candles[Timeframe.H4]
H1_REG = classify_regime(H1_DF["close"])
H4_REG = classify_regime(H4_DF["close"])
KELLY_CAP = float(SETTINGS.risk_per_trade_pct) / 100.0
KELLY_FRAC = float(SETTINGS.kelly_fraction)


def _report(timeframe: str = "1h", **over: Any) -> dict[str, Any]:
    reg = H1_REG if timeframe == "1h" else H4_REG
    base: dict[str, Any] = {
        "symbol": SYMBOL,
        "timeframe": timeframe,
        "regime": reg.label.value,
        "stats": reg.stats.model_dump(mode="json"),
        "playbook": "TREND_FOLLOWING" if reg.label is RegimeLabel.TRENDING else "NO_TRADE",
        "kelly": None,
        "reasoning": "Lectura de prueba coherente con el régimen.",
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


async def _run(model: FunctionModel, deps: AgentDeps | None = None) -> Any:
    with quant_agent.override(model=model):
        return await quant_agent.run("Analiza EUR/USD", deps=deps or _deps())


def _returns(messages: list[ModelMessage], tool: str) -> list[Any]:
    return [
        p.content
        for m in messages
        if isinstance(m, ModelRequest)
        for p in m.parts
        if isinstance(p, ToolReturnPart) and p.tool_name == tool
    ]


def _retries(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [
        p
        for m in messages
        if isinstance(m, ModelRequest)
        for p in m.parts
        if isinstance(p, ToolReturnPart) and p.outcome == "retried"
    ]


def test_fixture_regimes_are_as_expected() -> None:
    assert H1_REG.label is RegimeLabel.TRENDING
    assert H4_REG.label is RegimeLabel.MEAN_REVERTING


async def test_tools_return_exactly_the_pure_functions() -> None:
    seen: dict[str, list[ModelMessage]] = {}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not _returns(messages, "get_features"):
            return ModelResponse(
                parts=[
                    ToolCallPart("get_features", {"timeframe": "1h"}),
                    ToolCallPart(
                        "get_features", {"timeframe": "4h", "vol_window": 30, "atr_period": 10}
                    ),
                    ToolCallPart("get_regime_stats", {"timeframe": "1h"}),
                    ToolCallPart("get_regime_stats", {"timeframe": "4h", "zscore_window": 30}),
                    ToolCallPart("classify", {"timeframe": "1h"}),
                    ToolCallPart("classify", {"timeframe": "4h"}),
                ]
            )
        seen["m"] = messages
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, _report())])

    await _run(FunctionModel(respond))
    m = seen["m"]

    def feats(df: pl.DataFrame, w: int, p: int) -> dict[str, Any]:
        row = df.select(r=log_returns(), v=rolling_volatility(w), a=atr(p)).tail(1)
        return {
            "n_obs": df.height,
            "vol_window": w,
            "atr_period": p,
            "log_return": row["r"][0],
            "volatility": row["v"][0],
            "atr": row["a"][0],
        }

    got = _returns(m, "get_features")
    assert got == [
        {"timeframe": "1h", **feats(H1_DF, 20, 14)},
        {"timeframe": "4h", **feats(H4_DF, 30, 10)},
    ]

    def stats(df: pl.DataFrame, w: int) -> dict[str, Any]:
        close = df["close"]
        return {
            "n_obs": df.height,
            "zscore_window": w,
            "hurst": hurst_exponent(close.to_numpy()),
            "adf_pvalue": adf_pvalue(close.to_numpy()),
            "zscore": zscore(close, w).tail(1)[0],
        }

    assert _returns(m, "get_regime_stats") == [
        {"timeframe": "1h", **stats(H1_DF, 50)},
        {"timeframe": "4h", **stats(H4_DF, 30)},
    ]
    assert _returns(m, "classify") == [
        H1_REG.model_dump(mode="json"),
        H4_REG.model_dump(mode="json"),
    ]


async def test_valid_report_passes() -> None:
    model, calls = _sequence([_report()])
    result = await _run(model)
    assert calls[0] == 1
    assert result.output.regime is RegimeLabel.TRENDING
    assert result.output.playbook is Playbook.TREND_FOLLOWING


@pytest.mark.parametrize(
    "bad",
    [
        {"regime": "MEAN_REVERTING"},
        {"stats": {**H1_REG.stats.model_dump(mode="json"), "hurst": 0.123}},
        {"stats": {**H1_REG.stats.model_dump(mode="json"), "n_obs": 5}},
        {"symbol": "BTC/USDT"},
        {"timeframe": "1d"},
    ],
    ids=["regimen", "hurst", "n_obs", "symbol", "timeframe"],
)
async def test_inconsistent_report_is_rejected_then_corrected(bad: dict[str, Any]) -> None:
    model, calls = _sequence([_report(**bad), _report()])
    result = await _run(model)
    assert calls[0] == 2
    assert len(_retries(result.all_messages())) == 1
    assert result.output.regime is RegimeLabel.TRENDING


async def test_wrong_regime_always_fails() -> None:
    model, calls = _sequence([_report(regime="MEAN_REVERTING")])
    with pytest.raises(UnexpectedModelBehavior):
        await _run(model)
    assert calls[0] == 3


async def test_regime_is_checked_against_the_report_timeframe() -> None:
    model, calls = _sequence([_report("4h")])
    result = await _run(model)
    assert calls[0] == 1
    assert result.output.regime is RegimeLabel.MEAN_REVERTING


async def test_playbook_against_regime_is_accepted_only_when_annotated() -> None:
    plain = _report(playbook="MEAN_REVERSION")
    noted = _report(
        playbook="MEAN_REVERSION",
        reasoning="Operar contra el régimen TRENDING: es una hipótesis de contratendencia.",
    )
    model, calls = _sequence([plain, noted])
    result = await _run(model)
    assert calls[0] == 2
    assert result.output.playbook is Playbook.MEAN_REVERSION
    assert result.output.regime is RegimeLabel.TRENDING
    assert "contra el régimen" in result.output.reasoning
    (retry,) = _retries(result.all_messages())
    assert "contra el régimen" in str(retry.content)


async def test_annotated_mismatch_is_accepted_at_first_attempt() -> None:
    noted = _report(playbook="MEAN_REVERSION", reasoning="Contra el régimen: contratendencia.")
    model, calls = _sequence([noted])
    result = await _run(model)
    assert calls[0] == 1
    assert result.output.playbook is Playbook.MEAN_REVERSION


async def test_kelly_tool_returns_kelly_fraction_and_marks_it_uncalibrated() -> None:
    seen: dict[str, list[ModelMessage]] = {}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not _returns(messages, "kelly"):
            return ModelResponse(parts=[ToolCallPart("kelly", {"p": 0.55, "b": 2.0})])
        seen["m"] = messages
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, _report())])

    await _run(FunctionModel(respond))
    (got,) = _returns(seen["m"], "kelly")
    expected = kelly_fraction(0.55, 2.0, KELLY_FRAC, KELLY_CAP)
    assert got["kelly"] == expected.model_dump(mode="json")
    assert got["p"] == 0.55
    assert got["b"] == 2.0
    assert got["informativo"] is True
    assert got["calibrado"] is False
    assert "sin calibrar" in got["aviso"]


def _kelly_report(p: float = 0.55, b: float = 2.0, **over: Any) -> dict[str, Any]:
    k = kelly_fraction(p, b, KELLY_FRAC, KELLY_CAP).model_dump(mode="json")
    base = {"kelly": k, "reasoning": "Kelly informativo, p y b sin calibrar."}
    base.update(over)
    return _report(**base)


def _kelly_then(reports: list[dict[str, Any]], p: float, b: float) -> FunctionModel:
    calls = [0]

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not _returns(messages, "kelly"):
            return ModelResponse(parts=[ToolCallPart("kelly", {"p": p, "b": b})])
        rep = reports[min(calls[0], len(reports) - 1)]
        calls[0] += 1
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, rep)])

    return FunctionModel(respond)


async def test_kelly_from_tool_is_accepted() -> None:
    result = await _run(_kelly_then([_kelly_report()], 0.55, 2.0))
    assert result.output.kelly == kelly_fraction(0.55, 2.0, KELLY_FRAC, KELLY_CAP)


async def test_kelly_without_calling_tool_is_rejected() -> None:
    model, calls = _sequence([_kelly_report(), _report()])
    result = await _run(model)
    assert calls[0] == 2
    assert result.output.kelly is None
    (retry,) = _retries(result.all_messages())
    assert "kelly" in str(retry.content)


async def test_kelly_not_matching_tool_is_rejected_then_corrected() -> None:
    invented = _kelly_report(kelly={"full_kelly": 0.9, "fraction": 0.2, "capped": False})
    result = await _run(_kelly_then([invented, _kelly_report()], 0.55, 2.0))
    assert len(_retries(result.all_messages())) == 1
    assert result.output.kelly == kelly_fraction(0.55, 2.0, KELLY_FRAC, KELLY_CAP)


async def test_kelly_computed_for_other_p_b_is_rejected() -> None:
    other = _kelly_report(p=0.7, b=3.0)
    model = _kelly_then([other], 0.55, 2.0)
    with pytest.raises(UnexpectedModelBehavior):
        await _run(model)


async def test_kelly_requires_uncalibrated_mention() -> None:
    silent = _kelly_report(reasoning="Kelly calculado.")
    result = await _run(_kelly_then([silent, _kelly_report()], 0.55, 2.0))
    assert len(_retries(result.all_messages())) == 1
    assert "sin calibrar" in result.output.reasoning


async def test_kelly_tool_invalid_inputs_are_retried() -> None:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("kelly", {"p": 1.5, "b": 2.0})])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, _report())])

    result = await _run(FunctionModel(respond))
    assert len(_retries(result.all_messages())) == 1


async def test_kelly_state_is_per_deps_not_global() -> None:
    first = _deps()
    await _run(_kelly_then([_kelly_report()], 0.55, 2.0), first)
    # Otro contexto de ejecución no hereda la llamada a la herramienta.
    model, _ = _sequence([_kelly_report()])
    with pytest.raises(UnexpectedModelBehavior):
        await _run(model, _deps())


async def test_unknown_timeframe_tool_call_is_retried() -> None:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("classify", {"timeframe": "1d"})])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, _report())])

    result = await _run(FunctionModel(respond))
    assert result.output.symbol == SYMBOL


async def test_trace_contains_prompt_version_and_prompt() -> None:
    model, _ = _sequence([_report()])
    with quant_agent.override(model=model):
        run = await run_agent(quant_agent, "Analiza EUR/USD", _deps(), settings=SETTINGS)
    assert run.trace["prompt_version"] == PROMPT_VERSION
    assert QUANT_PROMPT in run.trace["system_prompt"]
