"""Tests `db` del orquestador de análisis con velas sintéticas y `FunctionModel` guionizados.

Sin red: los tres agentes responden con modelos de `FunctionModel` (D84). Los informes
guionizados se construyen con los mismos datos que lee el orquestador (`fetch_latest`) para que
pasen los `output_validator` reales.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import numpy as np
import pytest
from pydantic import TypeAdapter
from pydantic_ai import ModelResponse, RequestUsage, ToolCallPart
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from app.agents.models import (
    AgentRole,
    AgentsNotConfiguredError,
    ModelFactory,
    default_model_factory,
)
from app.core.config import Settings, get_settings
from app.core.db import build_engine
from app.models.agent_analysis import AgentAnalysis
from app.models.trade_signal import TradeSignal
from app.quant.data import candles_to_frame
from app.quant.regime import classify_regime
from app.quant.structure import analyze_structure
from app.repositories import agent_analyses as steps_repo
from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as ohlcv_repo
from app.risk.kelly import kelly_fraction
from app.risk.sizing import position_size
from app.schemas.analysis import (
    AgentReportSchema,
    AnalysisCompleted,
    AnalysisEvent,
    AnalysisFailed,
    AnalyzeRequest,
    StepCompleted,
    StepFailed,
)
from app.schemas.candle import CandleSchema
from app.schemas.enums import (
    AnalysisOutcome,
    AnalysisStep,
    SignalStatus,
    SwingKind,
    Timeframe,
    VetoReason,
)
from app.schemas.quant import RegimeReport, SwingPoint
from app.schemas.risk import PortfolioState
from app.schemas.signals import AUDITOR_REJECTION_MARKER, ProposedSignal
from app.services import analysis as analysis_module
from app.services.analysis import (
    InstrumentNotFoundError,
    InsufficientDataError,
    InsufficientTimeframesError,
    analyze,
)
from app.services.portfolio import SIMULATED_PORTFOLIO_WARNING
from tests.quant.synthetic import mean_reverting, random_walk, trending

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("use_test_db")]

T0 = datetime(2026, 1, 1, tzinfo=UTC)
SYMBOL = "EUR/USD"
LOOKBACK = 300
KEY = "sk-ant-api03-SECRETO-DE-PRUEBA-123456"
EVENTS: TypeAdapter[AnalysisEvent] = TypeAdapter(AnalysisEvent)
ALL_STEPS = [
    AnalysisStep.STRUCTURE,
    AnalysisStep.QUANT,
    AnalysisStep.PROPOSAL,
    AnalysisStep.GUARDS,
    AnalysisStep.RISK_AUDIT,
]


def make_settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {"analysis_lookback_bars": LOOKBACK, "anthropic_api_key": KEY}
    return Settings(_env_file=None, **(base | kw))  # type: ignore[call-arg]


# --- datos ------------------------------------------------------------------------------


def _price(p: float) -> Decimal:
    return Decimal(str(round(float(p), 4)))


async def seed(
    session: AsyncSession,
    symbol: str,
    tf: Timeframe,
    prices: np.ndarray[Any, Any],
) -> None:
    row = await instruments_repo.get_by_symbol(session, symbol)
    assert row is not None
    candles = [
        CandleSchema(
            symbol=symbol,
            timeframe=tf,
            ts=T0 + i * tf.duration,
            open=_price(p),
            high=_price(p + 0.5),
            low=_price(p - 0.5),
            close=_price(p),
            volume=Decimal(10),
        )
        for i, p in enumerate(prices)
    ]
    await ohlcv_repo.upsert_candles(session, row.id, candles)
    await session.commit()


H1_PRICES = trending(400, seed=7)
XAU_PRICES = H1_PRICES * 2
BTC_PRICES = random_walk(400, seed=11)


async def seed_world(session: AsyncSession) -> None:
    await seed(session, SYMBOL, Timeframe.M15, mean_reverting(400, seed=1))
    await seed(session, SYMBOL, Timeframe.H1, H1_PRICES)
    await seed(session, SYMBOL, Timeframe.H4, mean_reverting(400, seed=3))
    await seed(session, SYMBOL, Timeframe.D1, mean_reverting(400, seed=4))
    await seed(session, "XAU/USD", Timeframe.H1, XAU_PRICES)
    await seed(session, "BTC/USDT", Timeframe.H1, BTC_PRICES)


@dataclass(frozen=True)
class Truth:
    last_close: Decimal
    low: SwingPoint
    regime: RegimeReport


async def truth(session: AsyncSession) -> Truth:
    row = await instruments_repo.get_by_symbol(session, SYMBOL)
    assert row is not None
    candles = await ohlcv_repo.fetch_latest(session, row.id, Timeframe.H1, LOOKBACK, SYMBOL)
    frame = candles_to_frame(candles)
    last = candles[-1].close
    lows = [
        s for s in analyze_structure(frame).swings if s.kind is SwingKind.LOW and s.price < last
    ]
    assert lows, "la serie sintética debe tener un swing low bajo el último cierre"
    return Truth(last, lows[-1], classify_regime(frame["close"]))


# --- modelos guionizados ----------------------------------------------------------------


def structure_report(t: Truth, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "symbol": SYMBOL,
        "entry_timeframe": "1h",
        "timeframes": [
            {
                "timeframe": "1h",
                "bias": "BULLISH",
                "last_event": None,
                "key_levels": [str(t.low.price)],
                "open_fvg_ts": [],
                "comment": "Sesgo alcista en 1h.",
            },
            {
                "timeframe": "4h",
                "bias": "NEUTRAL",
                "last_event": None,
                "key_levels": [],
                "open_fvg_ts": [],
                "comment": "Sin estructura clara en 4h.",
            },
        ],
        "htf_alignment": "BULLISH",
        "zone_ts": None,
        "invalidation_level": str(t.low.price),
        "reasoning": "Hipótesis: continuación alcista mientras no se pierda el último mínimo.",
    }
    return base | over


def quant_report(t: Truth, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "symbol": SYMBOL,
        "timeframe": "1h",
        "regime": t.regime.label.value,
        "stats": t.regime.stats.model_dump(mode="json"),
        "playbook": "TREND_FOLLOWING",
        "kelly": None,
        "reasoning": "Régimen con tendencia según Hurst; hipótesis de seguimiento.",
    }
    return base | over


APPROVE = {"decision": "APPROVE", "concerns": [], "rationale": "Sin objeciones verificables."}
VETO = {"decision": "VETO", "concerns": ["Fuente incoherente"], "rationale": "No se confirma."}


def scripted(
    report: dict[str, Any] | None = None,
    *,
    usage: RequestUsage | None = None,
    fail: Exception | None = None,
    calls: list[int] | None = None,
    delay: float = 0.003,
) -> FunctionModel:
    """Modelo que responde `report` (con latencia) o lanza `fail`; registra cada invocación."""

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if calls is not None:
            calls.append(1)
        await asyncio.sleep(delay)
        if fail is not None:
            raise fail
        parts = [ToolCallPart(info.output_tools[0].name, report or {})]
        if usage is not None:
            return ModelResponse(parts=parts, usage=usage)
        return ModelResponse(parts=parts)

    return FunctionModel(respond)  # type: ignore[arg-type]


def factory_of(structure: Model, quant: Model, auditor: Model) -> ModelFactory:
    models = {
        AgentRole.STRUCTURE: structure,
        AgentRole.QUANT: quant,
        AgentRole.AUDITOR: auditor,
    }
    return lambda role: models[role]


def happy_factory(t: Truth, **kw: Any) -> ModelFactory:
    return factory_of(
        scripted(structure_report(t)),
        scripted(quant_report(t)),
        scripted(kw.get("auditor", APPROVE)),
    )


def request(**kw: Any) -> AnalyzeRequest:
    return AnalyzeRequest.model_validate({"symbol": SYMBOL} | kw)


async def run(
    session: AsyncSession,
    factory: ModelFactory,
    settings: Settings | None = None,
    req: AnalyzeRequest | None = None,
) -> list[AnalysisEvent]:
    stream = await analyze(session, req or request(), settings or make_settings(), factory)
    return [e async for e in stream]


async def step_rows(session: AsyncSession, analysis_id: Any) -> list[AgentAnalysis]:
    return await steps_repo.list_by_analysis(session, analysis_id)


async def n_rows(session: AsyncSession, model: type[Any]) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


def completed_report(events: list[AnalysisEvent]) -> AgentReportSchema:
    last = events[-1]
    assert isinstance(last, AnalysisCompleted), last
    return last.report


@pytest.fixture
async def other() -> AsyncIterator[AsyncSession]:
    """Sesión independiente: solo ve lo confirmado (`commit`) por el orquestador."""
    engine = build_engine(get_settings().test_database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            yield s
    finally:
        await engine.dispose()


# --- camino feliz -----------------------------------------------------------------------


async def test_camino_feliz_cinco_pasos_y_senal_aprobada(
    db_session: AsyncSession, other: AsyncSession
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    stream = await analyze(db_session, request(), make_settings(), happy_factory(t))

    events: list[AnalysisEvent] = []
    seen_steps: list[AnalysisStep] = []
    async for event in stream:
        events.append(event)
        if isinstance(event, StepCompleted):
            seen_steps.append(event.step)
            # Persistido y confirmado ANTES de emitir el evento (D85).
            rows = await step_rows(other, event.analysis_id)
            assert [AnalysisStep(r.step) for r in rows] == seen_steps

    report = completed_report(events)
    assert report.outcome is AnalysisOutcome.SIGNAL_APPROVED
    assert [e.seq for e in events] == list(range(len(events)))
    assert [e.event for e in events] == [
        "analysis_started",
        *[name for _ in ALL_STEPS for name in ("step_started", "step_completed")],
        "analysis_completed",
    ]
    for e in events:  # cada evento valida contra el contrato
        EVENTS.validate_json(e.model_dump_json())

    rows = await step_rows(db_session, report.analysis_id)
    assert [AnalysisStep(r.step) for r in rows] == ALL_STEPS
    assert {r.analysis_id for r in rows} == {report.analysis_id}
    assert all(r.status == "OK" and r.timeframe == "1h" for r in rows)
    for r in rows:
        if r.step in ("STRUCTURE", "QUANT", "RISK_AUDIT"):
            assert r.input_tokens > 0 and r.output_tokens > 0 and r.latency_ms > 0
            assert r.model is not None and r.trace is not None
            assert r.trace["prompt_version"]
        else:  # pasos de código: sin tokens ni modelo
            assert (r.input_tokens, r.output_tokens, r.model) == (0, 0, None)
    guards_row = next(r for r in rows if r.step == "GUARDS")
    assert guards_row.output is not None and guards_row.output["approved"] is True

    signals = (await db_session.execute(select(TradeSignal))).scalars().all()
    assert len(signals) == 1
    row = signals[0]
    assert row.status == "APPROVED" and row.analysis_id == report.analysis_id
    assert report.signal is not None and row.id == report.signal.id
    assert report.signal.status is SignalStatus.APPROVED
    assert report.signal.size is not None and report.signal.size.units > 0
    assert report.signal.size.risk_pct <= get_settings().risk_per_trade_pct
    assert report.signal.rr >= get_settings().min_rr
    assert report.signal.veto_reasons == []
    assert report.proposal is not None and report.risk_verdict is not None
    assert report.signal.entry == t.last_close
    assert report.usage.input_tokens == sum(r.input_tokens for r in rows)
    assert report.usage.latency_ms == sum(r.latency_ms for r in rows)
    assert SIMULATED_PORTFOLIO_WARNING in report.warnings
    assert any("Sin tope de coste" in w for w in report.warnings)
    assert any("Yahoo" in w for w in report.warnings)


async def test_los_pasos_de_codigo_guardan_entrada_y_salida(db_session: AsyncSession) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    report = completed_report(await run(db_session, happy_factory(t)))

    rows = {r.step: r for r in await step_rows(db_session, report.analysis_id)}
    proposal_row = rows["PROPOSAL"]
    assert proposal_row.output is not None and proposal_row.output["no_trade_reason"] is None
    assert proposal_row.output["proposal"]["direction"] == "LONG"
    assert proposal_row.input["playbook"] == "TREND_FOLLOWING"
    assert proposal_row.input["params"] == {"target_rr": "2.0", "sl_atr_buffer": "0.5"}
    assert rows["RISK_AUDIT"].output is not None
    assert rows["RISK_AUDIT"].output["final_status"] == "APPROVED"


# --- veto determinista -------------------------------------------------------------------


async def test_veto_determinista_por_rr_no_invoca_al_auditor(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    real = analysis_module.build_proposal

    def low_rr(*args: Any, **kwargs: Any) -> Any:
        res = real(*args, **kwargs)
        assert isinstance(res, ProposedSignal)
        tp = (res.entry + (res.entry - res.stop_loss) * Decimal("1.5")).quantize(Decimal("0.00001"))
        return res.model_copy(update={"take_profit": tp, "rr": Decimal("1.5")})

    monkeypatch.setattr(analysis_module, "build_proposal", low_rr)
    auditor_calls: list[int] = []
    factory = factory_of(
        scripted(structure_report(t)),
        scripted(quant_report(t)),
        scripted(APPROVE, calls=auditor_calls),
    )

    report = completed_report(await run(db_session, factory))

    assert report.outcome is AnalysisOutcome.SIGNAL_REJECTED
    assert auditor_calls == []
    rows = await step_rows(db_session, report.analysis_id)
    assert [AnalysisStep(r.step) for r in rows] == ALL_STEPS[:4]
    assert report.guards is not None and report.guards.approved is False
    assert report.guards.reasons == [VetoReason.RR_BELOW_MIN]
    assert report.risk_verdict is None
    assert report.signal is not None
    assert report.signal.status is SignalStatus.REJECTED
    assert report.signal.veto_reasons == [VetoReason.RR_BELOW_MIN]
    stored = (await db_session.execute(select(TradeSignal))).scalars().one()
    assert stored.status == "REJECTED" and stored.veto_reasons == ["RR_BELOW_MIN"]
    assert stored.analysis_id == report.analysis_id


async def test_veto_determinista_por_perdida_diaria(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)

    async def losing(session: AsyncSession, settings: Settings) -> tuple[PortfolioState, list[str]]:
        state = PortfolioState(
            equity=Decimal(10000),
            day_start_equity=Decimal(10000),
            realized_pnl_today=Decimal(-300),  # 3 % = límite exacto
            open_positions=[],
        )
        return state, [SIMULATED_PORTFOLIO_WARNING]

    monkeypatch.setattr(analysis_module, "load_portfolio_state", losing)
    report = completed_report(await run(db_session, happy_factory(t)))

    assert report.outcome is AnalysisOutcome.SIGNAL_REJECTED
    assert report.signal is not None
    assert VetoReason.DAILY_LOSS_LIMIT in report.signal.veto_reasons
    rows = await step_rows(db_session, report.analysis_id)
    assert "RISK_AUDIT" not in [r.step for r in rows]


# --- NO_TRADE y auditor ------------------------------------------------------------------


async def test_no_trade_sin_senal_y_con_motivo(db_session: AsyncSession) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    factory = factory_of(
        scripted(structure_report(t)),
        scripted(quant_report(t, playbook="NO_TRADE")),
        scripted(APPROVE),
    )

    report = completed_report(await run(db_session, factory))

    assert report.outcome is AnalysisOutcome.NO_TRADE
    assert report.signal is None and report.proposal is None and report.guards is None
    assert any("NO_TRADE" in w and w.startswith("Sin operación") for w in report.warnings)
    rows = await step_rows(db_session, report.analysis_id)
    assert [AnalysisStep(r.step) for r in rows] == ALL_STEPS[:3]
    assert rows[2].output is not None and "NO_TRADE" in rows[2].output["no_trade_reason"]
    assert await n_rows(db_session, TradeSignal) == 0


async def test_veto_del_auditor_deja_la_senal_rechazada(db_session: AsyncSession) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    report = completed_report(await run(db_session, happy_factory(t, auditor=VETO)))

    assert report.outcome is AnalysisOutcome.SIGNAL_REJECTED
    assert report.signal is not None
    assert report.signal.status is SignalStatus.REJECTED
    assert report.signal.veto_reasons == []
    assert AUDITOR_REJECTION_MARKER in report.signal.rationale
    assert "Fuente incoherente" in report.signal.rationale
    assert report.risk_verdict is not None
    assert report.risk_verdict.deterministic.approved is True  # lo copia el código
    rows = await step_rows(db_session, report.analysis_id)
    assert [AnalysisStep(r.step) for r in rows] == ALL_STEPS
    stored = (await db_session.execute(select(TradeSignal))).scalars().one()
    assert stored.status == "REJECTED" and AUDITOR_REJECTION_MARKER in (stored.rationale or "")


# --- fallos ------------------------------------------------------------------------------


@pytest.mark.parametrize("failing", ["STRUCTURE", "QUANT", "AUDITOR"])
async def test_fallo_de_un_agente_deja_fila_error_y_analysis_failed(
    db_session: AsyncSession, failing: str
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    boom = RuntimeError("el proveedor devolvió 500")
    models: dict[str, Model] = {
        "STRUCTURE": scripted(structure_report(t)),
        "QUANT": scripted(quant_report(t)),
        "AUDITOR": scripted(APPROVE),
    }
    models[failing] = scripted(fail=boom)
    factory = factory_of(models["STRUCTURE"], models["QUANT"], models["AUDITOR"])

    events = await run(db_session, factory)

    step = {"STRUCTURE": "STRUCTURE", "QUANT": "QUANT", "AUDITOR": "RISK_AUDIT"}[failing]
    assert [e.event for e in events[-2:]] == ["step_failed", "analysis_failed"]
    failed, last = events[-2], events[-1]
    assert isinstance(failed, StepFailed) and isinstance(last, AnalysisFailed)
    assert failed.step.value == step and last.step is not None and last.step.value == step
    assert "el proveedor devolvió 500" in last.error
    assert not any(isinstance(e, AnalysisCompleted) for e in events)
    rows = await step_rows(db_session, events[0].analysis_id)
    assert rows[-1].step == step and rows[-1].status == "ERROR"
    assert rows[-1].output is None and "el proveedor devolvió 500" in (rows[-1].error or "")
    assert [r.status for r in rows[:-1]] == ["OK"] * (len(rows) - 1)
    assert await n_rows(db_session, TradeSignal) == 0


async def test_salida_invalida_tras_reintentos_es_un_fallo_auditado(
    db_session: AsyncSession,
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    bad = structure_report(t, invalidation_level="12345.6789")  # no existe en las herramientas
    factory = factory_of(scripted(bad), scripted(quant_report(t)), scripted(APPROVE))

    events = await run(db_session, factory)

    assert isinstance(events[-1], AnalysisFailed)
    rows = await step_rows(db_session, events[0].analysis_id)
    assert [(r.step, r.status) for r in rows] == [("STRUCTURE", "ERROR")]


async def test_marco_de_entrada_distinto_en_el_informe_falla_con_su_consumo(
    db_session: AsyncSession,
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    # Sin invalidación: el validador del agente la exige en el marco de entrada (D111).
    wrong = structure_report(t, entry_timeframe="4h", invalidation_level=None)
    factory = factory_of(scripted(wrong), scripted(quant_report(t)), scripted(APPROVE))

    events = await run(db_session, factory)

    last = events[-1]
    assert isinstance(last, AnalysisFailed) and "entry_timeframe 4h" in last.error
    row = (await step_rows(db_session, events[0].analysis_id))[0]
    assert row.status == "ERROR" and row.input_tokens > 0 and row.trace is not None


async def test_tope_de_tokens_excedido_nombra_el_tope(db_session: AsyncSession) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    big = RequestUsage(input_tokens=5000, output_tokens=100)
    factory = factory_of(
        scripted(structure_report(t), usage=big), scripted(quant_report(t)), scripted(APPROVE)
    )

    events = await run(db_session, factory, make_settings(agent_max_tokens_per_analysis=1000))

    last = events[-1]
    assert isinstance(last, AnalysisFailed)
    assert "total_tokens_limit" in last.error
    assert "AGENT_MAX_TOKENS_PER_ANALYSIS=1000" in last.error
    assert "5100" in last.error  # consumo
    rows = await step_rows(db_session, last.analysis_id)
    assert [(r.step, r.status) for r in rows] == [("STRUCTURE", "ERROR")]


async def test_tope_de_coste_excedido_falla_el_paso_sin_guardar_senal(
    db_session: AsyncSession,
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    settings = make_settings(
        agent_price_input_usd_per_mtok=Decimal(1000),
        agent_price_output_usd_per_mtok=Decimal(1000),
        agent_max_cost_usd_per_analysis=Decimal("0.0001"),
    )
    usage = RequestUsage(input_tokens=1000, output_tokens=100)
    factory = factory_of(
        scripted(structure_report(t), usage=usage), scripted(quant_report(t)), scripted(APPROVE)
    )

    events = await run(db_session, factory, settings)

    last = events[-1]
    assert isinstance(last, AnalysisFailed)
    assert "AGENT_MAX_COST_USD_PER_ANALYSIS=0.0001" in last.error
    rows = await step_rows(db_session, last.analysis_id)
    assert [(r.step, r.status) for r in rows] == [("STRUCTURE", "ERROR")]
    assert rows[0].cost_usd is not None and rows[0].input_tokens == 1000
    assert await n_rows(db_session, TradeSignal) == 0


async def test_cost_usd_con_precios_y_sin_aviso_de_tope(db_session: AsyncSession) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    settings = make_settings(
        agent_price_input_usd_per_mtok=Decimal(3), agent_price_output_usd_per_mtok=Decimal(15)
    )

    report = completed_report(await run(db_session, happy_factory(t), settings))

    assert report.usage.cost_usd is not None and report.usage.cost_usd > 0
    rows = await step_rows(db_session, report.analysis_id)
    assert all(r.cost_usd is not None for r in rows if r.step in ("STRUCTURE", "QUANT"))
    assert any("Sin tope de coste" in w and "precios" not in w for w in report.warnings)


async def test_la_clave_no_aparece_en_ninguna_parte(db_session: AsyncSession) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    leaky = RuntimeError(f"401 x-api-key inválida: {KEY}")
    factory = factory_of(scripted(structure_report(t)), scripted(fail=leaky), scripted(APPROVE))

    events = await run(db_session, factory)
    ok_events = await run(db_session, happy_factory(t))

    dump = json.dumps([e.model_dump(mode="json") for e in [*events, *ok_events]], default=str)
    rows = (await db_session.execute(select(AgentAnalysis))).scalars().all()
    dump += json.dumps([[r.input, r.output, r.trace, r.error, r.model] for r in rows], default=str)
    assert KEY not in dump
    assert "[CLAVE OCULTA]" in dump
    assert KEY not in repr(make_settings())


async def test_la_clave_gemini_se_redacta_en_errores(db_session: AsyncSession) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    gemini = "AIza-GEMINI-SECRETO-DE-PRUEBA-789"
    settings = make_settings(agent_provider="google", gemini_api_key=gemini)
    leaky = RuntimeError(f"403 API key not valid: {gemini}")
    factory = factory_of(scripted(structure_report(t)), scripted(fail=leaky), scripted(APPROVE))

    events = await run(db_session, factory, settings=settings)

    dump = json.dumps([e.model_dump(mode="json") for e in events], default=str)
    rows = (await db_session.execute(select(AgentAnalysis))).scalars().all()
    dump += json.dumps([[r.input, r.output, r.trace, r.error, r.model] for r in rows], default=str)
    assert gemini not in dump
    assert "[CLAVE OCULTA]" in dump
    assert gemini not in repr(settings)


# --- validación previa -------------------------------------------------------------------


async def test_simbolo_desconocido_antes_de_emitir(db_session: AsyncSession) -> None:
    with pytest.raises(InstrumentNotFoundError, match="Instrumento desconocido: XYZ"):
        await analyze(db_session, request(symbol="XYZ"), make_settings(), None)
    assert await n_rows(db_session, AgentAnalysis) == 0


async def test_sin_clave_lanza_agents_not_configured(db_session: AsyncSession) -> None:
    await seed_world(db_session)
    settings = Settings(_env_file=None, analysis_lookback_bars=LOOKBACK)  # type: ignore[call-arg]

    with pytest.raises(AgentsNotConfiguredError, match="ANTHROPIC_API_KEY"):
        await analyze(db_session, request(), settings)  # fábrica por defecto: build_model
    with pytest.raises(AgentsNotConfiguredError):
        await analyze(db_session, request(), settings, default_model_factory(settings))
    assert await n_rows(db_session, AgentAnalysis) == 0


async def test_orden_de_validacion_datos_antes_que_configuracion(
    db_session: AsyncSession,
) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]  # sin clave ni datos
    with pytest.raises(InsufficientDataError):
        await analyze(db_session, request(), settings)


async def test_marcos_sin_datos_se_omiten_con_aviso(db_session: AsyncSession) -> None:
    await seed(db_session, SYMBOL, Timeframe.H1, H1_PRICES)
    await seed(db_session, SYMBOL, Timeframe.H4, mean_reverting(400, seed=3))
    await seed(db_session, SYMBOL, Timeframe.M15, mean_reverting(50, seed=1))  # < 100 velas
    t = await truth(db_session)
    factory = factory_of(
        scripted(structure_report(t)),
        scripted(quant_report(t, playbook="NO_TRADE")),
        scripted(APPROVE),
    )

    events = await run(db_session, factory)  # pide 15m, 1h, 4h y 1d

    started = events[0]
    assert started.event == "analysis_started"
    assert getattr(started, "timeframes") == [Timeframe.H1, Timeframe.H4]  # noqa: B009
    report = completed_report(events)
    assert any("Marco 15m omitido" in w and "50 velas" in w for w in report.warnings)
    assert any("Marco 1d omitido" in w and "0 velas" in w for w in report.warnings)


async def test_menos_de_dos_marcos_es_datos_insuficientes(db_session: AsyncSession) -> None:
    await seed(db_session, SYMBOL, Timeframe.H1, H1_PRICES)

    with pytest.raises(InsufficientTimeframesError) as info:
        await analyze(db_session, request(), make_settings(), None)

    assert isinstance(info.value, InsufficientDataError)
    assert "1 marco(s)" in str(info.value) and "1h" in str(info.value)
    assert await n_rows(db_session, AgentAnalysis) == 0


async def test_marco_de_entrada_sin_datos_es_datos_insuficientes(db_session: AsyncSession) -> None:
    await seed(db_session, SYMBOL, Timeframe.H4, mean_reverting(400, seed=3))
    await seed(db_session, SYMBOL, Timeframe.D1, mean_reverting(400, seed=4))

    with pytest.raises(InsufficientDataError) as info:
        await analyze(db_session, request(), make_settings(), None)

    assert str(info.value) == (
        "Datos insuficientes para EUR/USD 1h: 0 velas, se necesitan al menos 100."
    )


# --- cartera y correlación ---------------------------------------------------------------


def _expected_rho(a: np.ndarray[Any, Any], b: np.ndarray[Any, Any], window: int) -> float:
    def rets(p: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        closes = np.array([float(_price(x)) for x in p[-(window + 1) :]])
        return np.diff(np.log(closes))

    return float(np.corrcoef(rets(a), rets(b))[0, 1])


async def test_las_guardas_usan_la_correlacion_real_de_los_cierres_de_la_bd(
    db_session: AsyncSession,
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    report = completed_report(await run(db_session, happy_factory(t)))

    rows = {r.step: r for r in await step_rows(db_session, report.analysis_id)}
    corr = {(c["a"], c["b"]): c["rho"] for c in rows["GUARDS"].input["correlations"]}
    window = get_settings().correlation_window
    assert set(corr) == {("BTC/USDT", "EUR/USD"), ("BTC/USDT", "XAU/USD"), ("EUR/USD", "XAU/USD")}
    assert corr[("EUR/USD", "XAU/USD")] == pytest.approx(1.0, abs=1e-9)  # XAU = 2 x EUR
    assert corr[("BTC/USDT", "EUR/USD")] == pytest.approx(
        _expected_rho(BTC_PRICES, H1_PRICES, window), abs=1e-9
    )
    assert abs(corr[("BTC/USDT", "EUR/USD")]) < 0.99
    portfolio = rows["GUARDS"].input["portfolio"]
    assert Decimal(portfolio["equity"]) == Decimal(portfolio["day_start_equity"]) == Decimal(10000)
    assert Decimal(portfolio["realized_pnl_today"]) == 0 and portfolio["open_positions"] == []


# --- cancelación -------------------------------------------------------------------------


async def test_cortar_el_iterador_tras_un_paso_conserva_solo_lo_confirmado(
    db_session: AsyncSession, other: AsyncSession
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    stream = await analyze(db_session, request(), make_settings(), happy_factory(t))

    analysis_id = None
    async for event in stream:
        analysis_id = event.analysis_id
        if isinstance(event, StepCompleted) and event.step is AnalysisStep.STRUCTURE:
            break
    await stream.aclose()

    assert analysis_id is not None
    rows = await step_rows(other, analysis_id)
    assert [r.step for r in rows] == ["STRUCTURE"]
    assert await n_rows(other, TradeSignal) == 0


async def test_cortar_tras_step_started_no_deja_filas(
    db_session: AsyncSession, other: AsyncSession
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    stream = await analyze(db_session, request(), make_settings(), happy_factory(t))

    first = await anext(stream)
    await anext(stream)  # step_started STRUCTURE
    await stream.aclose()

    assert await step_rows(other, first.analysis_id) == []


async def test_cancelar_la_tarea_durante_un_agente_no_deja_filas_parciales(
    db_session: AsyncSession, other: AsyncSession
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    entered = asyncio.Event()

    async def hang(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        entered.set()
        await asyncio.sleep(60)
        raise AssertionError("no debía terminar")

    factory = factory_of(
        FunctionModel(hang),  # type: ignore[arg-type]
        scripted(quant_report(t)),
        scripted(APPROVE),
    )
    stream = await analyze(db_session, request(), make_settings(), factory)
    ids: list[Any] = []

    async def consume() -> None:
        async for event in stream:
            ids.append(event.analysis_id)

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), timeout=10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await step_rows(other, ids[0]) == []
    assert await n_rows(other, TradeSignal) == 0


# --- factoría ----------------------------------------------------------------------------


async def test_la_fabrica_se_invoca_una_vez_por_rol(db_session: AsyncSession) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    roles: list[AgentRole] = []
    inner = happy_factory(t)

    def spy(role: AgentRole) -> Model:
        roles.append(role)
        return inner(role)

    await run(db_session, spy)

    assert sorted(roles) == sorted(AgentRole)


# --- Kelly no interviene en el tamaño (validation §1) -----------------------------------------


def kelly_quant(t: Truth, settings: Settings) -> FunctionModel:
    """Quant que llama a la herramienta `kelly(p, b)` y copia su resultado en el informe."""
    p, b = 0.51, 1.0  # Kelly fraccional 0,5 % < tope del 1 %: si interviniera, el tamaño cambiaría
    result = kelly_fraction(
        p,
        b,
        float(settings.kelly_fraction),
        float(settings.risk_per_trade_pct) / 100.0,
    )

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        called = any(
            isinstance(part, ToolReturnPart) and part.tool_name == "kelly"
            for m in messages
            if isinstance(m, ModelRequest)
            for part in m.parts
        )
        if not called:
            return ModelResponse(parts=[ToolCallPart("kelly", {"p": p, "b": b})])
        report = quant_report(
            t,
            kelly=result.model_dump(mode="json"),
            reasoning="Régimen con tendencia; Kelly informativo con p y b sin calibrar.",
        )
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, report)])

    return FunctionModel(respond)  # type: ignore[arg-type]


async def test_kelly_no_interviene_en_el_tamano(db_session: AsyncSession) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    settings = make_settings()
    row = await instruments_repo.get_by_symbol(db_session, SYMBOL)
    assert row is not None
    instrument = instruments_repo.to_schema(row)

    without = completed_report(await run(db_session, happy_factory(t), settings))
    with_kelly = completed_report(
        await run(
            db_session,
            factory_of(scripted(structure_report(t)), kelly_quant(t, settings), scripted(APPROVE)),
            settings,
        )
    )

    assert without.quant is not None and without.quant.kelly is None
    assert with_kelly.quant is not None and with_kelly.quant.kelly is not None
    assert with_kelly.quant.kelly.fraction < float(settings.risk_per_trade_pct) / 100
    a, b = without.signal, with_kelly.signal
    assert a is not None and b is not None and a.size is not None and b.size is not None
    assert (a.size.units, a.size.risk_amount) == (b.size.units, b.size.risk_amount)
    expected = position_size(
        settings.account_equity_usd,
        settings.risk_per_trade_pct,
        a.entry,
        a.stop_loss,
        instrument,
    )
    assert a.size.units == b.size.units == expected.units
    assert a.size.risk_amount == b.size.risk_amount == expected.risk_amount


# --- La clave no aparece en logs (validation §1) ---------------------------------------------

GEMINI_KEY = "AIza-GEMINI-SECRETO-DE-PRUEBA-789"


@pytest.mark.parametrize("provider", ["anthropic", "google"])
async def test_la_clave_no_aparece_en_los_logs(db_session: AsyncSession, provider: str) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    extra: dict[str, Any] = {"agent_model": "gemini-test"} if provider == "google" else {}
    settings = make_settings(agent_provider=provider, gemini_api_key=GEMINI_KEY, **extra)
    secret = GEMINI_KEY if provider == "google" else KEY
    leaky = RuntimeError(f"401 clave inválida: {secret}")
    factory = factory_of(scripted(structure_report(t)), scripted(fail=leaky), scripted(APPROVE))

    with capture_logs() as logs:
        events = await run(db_session, factory, settings)  # fallo de agente (analysis_step_failed)

    assert isinstance(events[-1], AnalysisFailed)
    assert any(entry["event"] == "analysis_step_failed" for entry in logs)
    assert KEY not in repr(logs) and GEMINI_KEY not in repr(logs)
    assert any("[CLAVE OCULTA]" in repr(entry) for entry in logs)


async def test_la_clave_no_aparece_en_los_logs_de_un_fallo_interno(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)

    def boom(frame: Any) -> Decimal:
        raise RuntimeError(f"fallo con {KEY} y {GEMINI_KEY}")

    monkeypatch.setattr(analysis_module, "_atr_decimal", boom)
    settings = make_settings(gemini_api_key=GEMINI_KEY)

    with capture_logs() as logs:
        events = await run(db_session, happy_factory(t), settings)

    assert any(entry["event"] == "analysis_internal_error" for entry in logs)
    assert KEY not in repr(logs) and GEMINI_KEY not in repr(logs)
    dump = json.dumps([e.model_dump(mode="json") for e in events], default=str)
    rows = (await db_session.execute(select(AgentAnalysis))).scalars().all()
    dump += json.dumps([[r.input, r.error] for r in rows], default=str)
    assert KEY not in dump and GEMINI_KEY not in dump


# --- Fallos internos: toda caída tras empezar un paso deja fila ERROR (D109) ----------------


def _failed_step(events: list[AnalysisEvent], step: str) -> StepFailed:
    assert [e.event for e in events[-2:]] == ["step_failed", "analysis_failed"]
    failed, last = events[-2], events[-1]
    assert isinstance(failed, StepFailed) and isinstance(last, AnalysisFailed)
    assert failed.step.value == step and last.step is not None and last.step.value == step
    assert not any(isinstance(e, AnalysisCompleted) for e in events)
    return failed


async def test_fallo_al_calcular_la_entrada_de_proposal_deja_fila_error(
    db_session: AsyncSession, other: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)

    def boom(frame: Any) -> Decimal:
        raise ValueError("atr roto")

    monkeypatch.setattr(analysis_module, "_atr_decimal", boom)

    events = await run(db_session, happy_factory(t))

    failed = _failed_step(events, "PROPOSAL")
    assert "Error interno del análisis: ValueError: atr roto" in failed.error
    rows = await step_rows(other, events[0].analysis_id)  # confirmado: lo ve otra sesión
    assert [(r.step, r.status) for r in rows] == [
        ("STRUCTURE", "OK"),
        ("QUANT", "OK"),
        ("PROPOSAL", "ERROR"),
    ]
    assert "atr roto" in (rows[-1].error or "") and rows[-1].output is None
    assert await n_rows(other, TradeSignal) == 0


async def test_fallo_entre_pasos_deja_fila_error_del_paso_empezado(
    db_session: AsyncSession, other: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)

    def boom(self: Any, structure: Any) -> str:
        raise RuntimeError("prompt roto")

    monkeypatch.setattr(analysis_module._Analysis, "_quant_prompt", boom)

    events = await run(db_session, happy_factory(t))

    _failed_step(events, "QUANT")
    rows = await step_rows(other, events[0].analysis_id)
    assert [(r.step, r.status) for r in rows] == [("STRUCTURE", "OK"), ("QUANT", "ERROR")]


class _ReportBoomError(Exception):
    pass


async def test_fallo_al_construir_el_informe_final_no_deja_senal_aprobada_huerfana(
    db_session: AsyncSession, other: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise _ReportBoomError("informe roto")

    monkeypatch.setattr(analysis_module, "AgentReportSchema", boom)

    events = await run(db_session, happy_factory(t))

    failed = _failed_step(events, "RISK_AUDIT")
    assert "falló al construir su resultado" in failed.error and "informe roto" in failed.error
    assert not any(
        isinstance(e, StepCompleted) and e.step is AnalysisStep.RISK_AUDIT for e in events
    )
    rows = await step_rows(other, events[0].analysis_id)
    assert [(r.step, r.status) for r in rows] == [
        ("STRUCTURE", "OK"),
        ("QUANT", "OK"),
        ("PROPOSAL", "OK"),
        ("GUARDS", "OK"),
        ("RISK_AUDIT", "ERROR"),
    ]
    assert rows[-1].input_tokens > 0  # conserva el consumo del auditor
    assert await n_rows(other, TradeSignal) == 0  # ninguna señal APPROVED huérfana
    assert [e.seq for e in events] == list(range(len(events)))  # sin huecos en `seq`


async def test_fallo_al_construir_el_informe_de_no_trade_y_de_veto(
    db_session: AsyncSession, other: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    monkeypatch.setattr(
        analysis_module,
        "AgentReportSchema",
        lambda **kw: (_ for _ in ()).throw(_ReportBoomError("informe roto")),
    )

    no_trade = factory_of(
        scripted(structure_report(t)),
        scripted(quant_report(t, playbook="NO_TRADE")),
        scripted(APPROVE),
    )
    events = await run(db_session, no_trade)
    _failed_step(events, "PROPOSAL")
    rows = await step_rows(other, events[0].analysis_id)
    assert [(r.step, r.status) for r in rows][-1] == ("PROPOSAL", "ERROR")

    async def losing(session: AsyncSession, settings: Settings) -> tuple[PortfolioState, list[str]]:
        state = PortfolioState(
            equity=Decimal(10000),
            day_start_equity=Decimal(10000),
            realized_pnl_today=Decimal(-300),
            open_positions=[],
        )
        return state, []

    monkeypatch.setattr(analysis_module, "load_portfolio_state", losing)
    events = await run(db_session, happy_factory(t))
    _failed_step(events, "GUARDS")
    rows = await step_rows(other, events[0].analysis_id)
    assert [(r.step, r.status) for r in rows][-1] == ("GUARDS", "ERROR")
    assert await n_rows(other, TradeSignal) == 0  # la señal REJECTED tampoco queda huérfana


async def test_fallo_del_commit_de_un_paso_deja_fila_error_y_ninguna_senal(
    db_session: AsyncSession, other: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    real_commit = db_session.commit
    calls = [0]

    async def flaky_commit() -> None:
        calls[0] += 1
        if calls[0] == 5:  # commit del paso RISK_AUDIT (OK + señal)
            raise RuntimeError("commit roto")
        await real_commit()

    monkeypatch.setattr(db_session, "commit", flaky_commit)

    events = await run(db_session, happy_factory(t))

    failed = _failed_step(events, "RISK_AUDIT")
    assert (
        "falló al confirmar en la base de datos" in failed.error and "commit roto" in failed.error
    )
    rows = await step_rows(other, events[0].analysis_id)
    assert [(r.step, r.status) for r in rows][-2:] == [("GUARDS", "OK"), ("RISK_AUDIT", "ERROR")]
    assert rows[-1].input_tokens > 0
    assert await n_rows(other, TradeSignal) == 0


async def test_si_la_auditoria_del_error_tambien_falla_el_analisis_termina_igual(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    real = steps_repo.insert_step

    async def picky(session: AsyncSession, **kw: Any) -> Any:
        if kw["status"].value == "ERROR":
            raise RuntimeError("bd caída")
        return await real(session, **kw)

    monkeypatch.setattr(analysis_module.steps_repo, "insert_step", picky)
    monkeypatch.setattr(
        analysis_module, "_atr_decimal", lambda frame: (_ for _ in ()).throw(ValueError("atr roto"))
    )

    with capture_logs() as logs:
        events = await run(db_session, happy_factory(t))

    assert isinstance(events[-1], AnalysisFailed) and "atr roto" in events[-1].error
    assert any(entry["event"] == "analysis_error_row_failed" for entry in logs)
    rows = await step_rows(db_session, events[0].analysis_id)
    assert [r.status for r in rows] == ["OK", "OK"]  # sin fila ERROR, pero sin colgarse


# --- Errores del SDK en español (D113) -------------------------------------------------------


async def test_un_error_http_del_proveedor_llega_traducido_y_sin_la_clave(
    db_session: AsyncSession,
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    boom = ModelHTTPError(503, "claude-x", body=f"overloaded {KEY}")
    factory = factory_of(scripted(structure_report(t)), scripted(fail=boom), scripted(APPROVE))

    events = await run(db_session, factory)

    last = events[-1]
    assert isinstance(last, AnalysisFailed)
    assert (
        "error del proveedor del modelo (ModelHTTPError, HTTP 503, modelo claude-x)" in last.error
    )
    assert "overloaded" in last.error and KEY not in last.error
    assert "[CLAVE OCULTA]" in last.error


async def test_salida_invalida_tras_reintentos_se_explica_en_espanol(
    db_session: AsyncSession,
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    bad = structure_report(t, invalidation_level="12345.6789")
    factory = factory_of(scripted(bad), scripted(quant_report(t)), scripted(APPROVE))

    events = await run(db_session, factory)

    last = events[-1]
    assert isinstance(last, AnalysisFailed)
    assert "el modelo no devolvió una salida válida tras agotar los reintentos" in last.error
    assert "UnexpectedModelBehavior" in last.error
    assert "invalidation_level 12345.6789" in last.error  # último rechazo del validador


async def test_el_timeout_del_agente_se_explica_en_espanol(db_session: AsyncSession) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    factory = factory_of(
        scripted(structure_report(t), delay=2), scripted(quant_report(t)), scripted(APPROVE)
    )

    events = await run(db_session, factory, make_settings(agent_timeout_s=0.05))

    last = events[-1]
    assert isinstance(last, AnalysisFailed)
    assert "AGENT_TIMEOUT_S=0.05" in last.error and "tiempo máximo por ejecución" in last.error
    rows = await step_rows(db_session, last.analysis_id)
    assert [(r.step, r.status) for r in rows] == [("STRUCTURE", "ERROR")]
