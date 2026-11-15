"""Orquestador de análisis multiagente (3.8, D85, D94-D96).

Flujo secuencial propio: ``STRUCTURE -> QUANT -> PROPOSAL (código) -> GUARDS (código) ->
RISK_AUDIT``. Cada paso se persiste en ``agent_analyses`` con ``commit`` ANTES de emitir su
evento, de modo que lo que el cliente ve ya está auditado.

API pública
-----------
``analyze(session, request, settings, model_factory=None)`` es una CORRUTINA que devuelve un
iterador asíncrono de ``AnalysisEvent``::

    stream = await analyze(session, request, settings, model_factory)   # puede lanzar
    async for event in stream: ...

Toda la validación (instrumento, datos, configuración) ocurre en el ``await`` y lanza
``InstrumentNotFoundError`` (404), ``InsufficientDataError`` (422) o ``AgentsNotConfiguredError``
(503) antes de emitir nada: el endpoint puede responder con HTTP real y solo después abrir el
*stream*. Los errores posteriores salen como eventos ``step_failed``/``analysis_failed``.

Decisiones de implementación
----------------------------
- ``model_factory: Callable[[AgentRole], Model]`` (``app.agents.models.ModelFactory``). Se invoca
  una vez por rol (STRUCTURE, QUANT, AUDITOR) durante la validación; si lanza
  ``AgentsNotConfiguredError`` (sin la clave del proveedor activo, D83) se propaga.
  Con ``None`` se usa
  ``default_model_factory(settings)``. El modelo se inyecta con ``Agent.override`` solo alrededor
  de la llamada al agente (nunca a través de un ``yield``).
- Orden de validación: instrumento -> datos -> configuración.
- Datos (D91): un marco con menos de ``MIN_BARS_PER_TIMEFRAME`` velas se omite con aviso; el marco
  de entrada sin datos suficientes o menos de 2 marcos útiles lanzan ``InsufficientDataError``.
- Tokens (D95): ``AGENT_MAX_TOKENS_PER_ANALYSIS`` se reparte entre los agentes que faltan (pesos
  5/3/2 para STRUCTURE/QUANT/RISK_AUDIT) sobre lo que queda; el último recibe todo el resto. El
  tope de coste solo se puede comprobar al terminar cada paso (el SDK no lo limita): se aplica
  sobre el coste acumulado y termina el análisis con ``analysis_failed``.
- Un paso fallido guarda su fila ``ERROR`` con los tokens conocidos (0 si el fallo ocurrió
  dentro del agente, que entonces no devuelve el consumo).
- Fallos internos (D109): todo fallo tras empezar un paso deja una fila ``ERROR`` auditada, también
  los de fuera del trabajo del paso (cálculo de la entrada, construcción del informe final,
  ``commit``). El informe y el ``AnalysisCompleted`` se construyen ANTES de confirmar el paso
  que cierra el análisis (y su señal): si construirlos falla, no se persiste ninguna señal y el
  paso queda en ``ERROR``. La fila ``ERROR`` se escribe en una transacción propia tras
  ``rollback``. Si el propio ``INSERT`` de auditoría falla, solo se registra en el log.
- Errores del SDK (D113): ``describe_step_error`` los traduce a español técnico.
- Cancelación: si el consumidor cierra el iterador o la tarea se cancela, se hace ``rollback`` y
  se re-lanza; como cada paso se confirma antes de emitirse, no quedan filas parciales.
- La clave de API nunca llega a ``input``/``trace``/errores: los mensajes de error se depuran.
"""

import asyncio
import math
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NoReturn

import polars as pl
import structlog
from pydantic_ai import Agent, UsageLimits
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.deps import AgentDeps
from app.agents.models import AgentRole, ModelFactory, default_model_factory
from app.agents.quant import quant_agent
from app.agents.risk_auditor import (
    build_audit_prompt,
    final_status,
    risk_auditor_agent,
    run_risk_audit,
)
from app.agents.runner import AgentRun, UsageLimitExceededError, run_agent
from app.agents.structure import structure_agent
from app.core.config import Settings
from app.models.agent_analysis import StepStatus
from app.quant.data import candles_to_frame
from app.quant.features import atr
from app.quant.proposal import NoTradeReason, ProposalParams, build_proposal
from app.quant.structure import analyze_structure
from app.repositories import agent_analyses as steps_repo
from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as ohlcv_repo
from app.risk.guards import evaluate_trade
from app.schemas.agents import MarketStructureReport, QuantAlphaReport, RiskVerdict
from app.schemas.analysis import (
    AgentReportSchema,
    AnalysisCompleted,
    AnalysisEvent,
    AnalysisFailed,
    AnalysisStarted,
    AnalyzeRequest,
    StepCompleted,
    StepFailed,
    StepStarted,
    StepUsage,
)
from app.schemas.candle import CandleSchema
from app.schemas.enums import AnalysisOutcome, AnalysisStep, Provider, SignalStatus, Timeframe
from app.schemas.instrument import InstrumentSchema
from app.schemas.risk import GuardDecision, PortfolioState, ProposedTrade
from app.schemas.signals import ProposedSignal, TradeSignalSchema, model_text
from app.services.backtest import InstrumentNotFoundError, InsufficientDataError
from app.services.portfolio import load_correlation_matrix, load_portfolio_state
from app.services.signals import build_trade_signal, persist_signal

__all__ = [
    "ATR_PERIOD",
    "MIN_BARS_PER_TIMEFRAME",
    "InstrumentNotFoundError",
    "InsufficientDataError",
    "InsufficientTimeframesError",
    "analyze",
    "describe_step_error",
]

MIN_BARS_PER_TIMEFRAME = 100  # `RegimeThresholds.min_obs`: mínimo para clasificar el régimen
ATR_PERIOD = 14
MAX_REQUESTS_PER_AGENT = 25
_TOKEN_WEIGHTS = {AnalysisStep.STRUCTURE: 5, AnalysisStep.QUANT: 3, AnalysisStep.RISK_AUDIT: 2}
# Peso de los agentes que faltan (incluido el actual): el reparto es peso_paso / peso_pendiente.
_PENDING_WEIGHT = {
    AnalysisStep.STRUCTURE: 10,
    AnalysisStep.QUANT: 5,
    AnalysisStep.RISK_AUDIT: 2,
}
_ROLES = {
    AnalysisStep.STRUCTURE: AgentRole.STRUCTURE,
    AnalysisStep.QUANT: AgentRole.QUANT,
    AnalysisStep.RISK_AUDIT: AgentRole.AUDITOR,
}
_MAX_ERROR_CHARS = 2000

_log = structlog.get_logger(__name__)


class InsufficientTimeframesError(InsufficientDataError):
    """Quedan menos de 2 marcos con datos suficientes (D91); la API responde 422."""

    def __init__(self, symbol: str, available: list[str], required_bars: int) -> None:
        super().__init__(symbol, "/".join(available) or "-", 0, required_bars)
        message = (
            f"Datos insuficientes para {symbol}: solo {len(available)} marco(s) con al menos "
            f"{required_bars} velas ({', '.join(available) or 'ninguno'}); se necesitan al menos 2."
        )
        self.args = (message,)


# --- Errores internos de control de flujo -------------------------------------------------


class _StepError(Exception):
    """Fallo de un paso con el consumo y la traza ya conocidos (p. ej. contrato incumplido)."""

    def __init__(
        self, message: str, usage: StepUsage | None = None, trace: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.usage = usage
        self.trace = trace


class _StepFailedError(Exception):
    """El paso ya quedó registrado como ERROR; el análisis termina."""

    def __init__(self, step: AnalysisStep, message: str, usage: StepUsage) -> None:
        super().__init__(message)
        self.step = step
        self.message = message
        self.usage = usage


@dataclass(frozen=True)
class _Outcome[T]:
    value: T
    output: dict[str, Any]
    usage: StepUsage
    trace: dict[str, Any] | None = None
    signal: TradeSignalSchema | None = None  # se inserta en la misma transacción del paso


@dataclass(frozen=True)
class _Done[T]:
    """Paso confirmado: su resultado y los eventos construidos ANTES del `commit` (D109)."""

    out: _Outcome[T]
    completed: StepCompleted
    final: AnalysisCompleted | None  # solo si este paso cierra el análisis


def _required[V](value: V | None) -> V:
    if value is None:
        raise RuntimeError("Evento final ausente en un paso que cierra el análisis")
    return value


# --- Utilidades ---------------------------------------------------------------------------


def describe_step_error(
    step: AnalysisStep, exc: Exception, *, timeout_s: float, max_tokens: int
) -> str:
    """Mensaje en español técnico de un fallo del agente, con el tipo y el dato útil (D113).

    No redacta claves (lo hace el llamador). Los casos conocidos del SDK (tope de uso, tiempo
    agotado, reintentos de salida agotados, errores del proveedor) se traducen; el resto conserva
    `Tipo: mensaje` original.
    """
    kind = type(exc).__name__
    if isinstance(exc, UsageLimitExceededError):
        return f"{exc} Tope por análisis: AGENT_MAX_TOKENS_PER_ANALYSIS={max_tokens}."
    if isinstance(exc, TimeoutError):  # incluye `RunTimedOut` del SDK
        return (
            f"El paso {step.value} superó el tiempo máximo por ejecución de agente "
            f"(AGENT_TIMEOUT_S={timeout_s:g} s): {kind}."
        )
    if isinstance(exc, UnexpectedModelBehavior):
        if "retries" in exc.message.lower():
            rejected = (
                f" Último rechazo: {model_text(str(exc.__cause__), 500)}" if exc.__cause__ else ""
            )
            return (
                f"El paso {step.value} falló: el modelo no devolvió una salida válida tras "
                f"agotar los reintentos ({kind}: {exc.message}).{rejected}"
            )
        return f"El paso {step.value} falló: comportamiento inesperado del modelo ({kind}): {exc}"
    if isinstance(exc, ModelHTTPError):
        return (
            f"El paso {step.value} falló: error del proveedor del modelo ({kind}, "
            f"HTTP {exc.status_code}, modelo {exc.model_name}): {model_text(str(exc.body), 500)}"
        )
    if isinstance(exc, ModelAPIError):
        return (
            f"El paso {step.value} falló: error de comunicación con el proveedor del modelo "
            f"({kind}, modelo {exc.model_name}): {exc.message}"
        )
    return f"El paso {step.value} falló: {kind}: {exc}"


def _json_safe(value: Any) -> Any:
    """Sustituye floats no finitos por `None` (JSONB no admite NaN ni infinitos)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    return value


def _atr_decimal(frame: pl.DataFrame) -> Decimal:
    """Último ATR(14). Frontera float -> Decimal: `Decimal(repr(x))`, sin ruido binario.

    Un ATR ausente o no finito se trata como 0 (`build_proposal` responde «sin propuesta»).
    """
    value = frame.select(atr(ATR_PERIOD).alias("atr"))["atr"][-1]
    if value is None or not math.isfinite(value):
        return Decimal(0)
    return Decimal(repr(float(value)))


def _type_msg(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _frame_meta(candles: list[CandleSchema]) -> dict[str, Any]:
    return {
        "n_bars": len(candles),
        "first_ts": candles[0].ts.isoformat(),
        "last_ts": candles[-1].ts.isoformat(),
        "last_close": str(candles[-1].close),
    }


# --- Validación previa (antes de emitir nada) -----------------------------------------------


async def analyze(
    session: AsyncSession,
    request: AnalyzeRequest,
    settings: Settings,
    model_factory: ModelFactory | None = None,
) -> AsyncGenerator[AnalysisEvent, None]:
    """Valida y prepara el análisis; devuelve el iterador de eventos (ver docstring del módulo).

    Lanza ``InstrumentNotFoundError``, ``InsufficientDataError`` (o su subclase
    ``InsufficientTimeframesError``) y ``AgentsNotConfiguredError`` antes de emitir nada.
    """
    factory = model_factory if model_factory is not None else default_model_factory(settings)

    row = await instruments_repo.get_by_symbol(session, request.symbol)
    if row is None:
        raise InstrumentNotFoundError(request.symbol)
    instrument = instruments_repo.to_schema(row)
    instrument_id = row.id

    candles: dict[Timeframe, list[CandleSchema]] = {}
    warnings: list[str] = []
    for tf in request.timeframes:
        got = await ohlcv_repo.fetch_latest(
            session, instrument_id, tf, settings.analysis_lookback_bars, instrument.symbol
        )
        if len(got) >= MIN_BARS_PER_TIMEFRAME:
            candles[tf] = got
        elif tf is request.timeframe:
            raise InsufficientDataError(
                instrument.symbol, tf.value, len(got), MIN_BARS_PER_TIMEFRAME
            )
        else:
            warnings.append(
                f"Marco {tf.value} omitido por datos insuficientes: {len(got)} velas "
                f"(mínimo {MIN_BARS_PER_TIMEFRAME})."
            )
    if len(candles) < 2:
        raise InsufficientTimeframesError(
            instrument.symbol, [tf.value for tf in candles], MIN_BARS_PER_TIMEFRAME
        )

    models = {role: factory(role) for role in AgentRole}  # AgentsNotConfiguredError -> 503

    portfolio, portfolio_warnings = await load_portfolio_state(session, settings)
    instruments = [(r.id, r.symbol) for r in await instruments_repo.list_all(session)]
    correlations = await load_correlation_matrix(
        session, instruments, request.timeframe, settings.correlation_window
    )

    warnings.extend(portfolio_warnings)
    if Provider(row.provider) is Provider.YAHOO:
        warnings.append("Datos provisionales de Yahoo Finance, no oficiales.")
    if settings.agent_max_cost_usd_per_analysis is None:
        priced = (
            settings.agent_price_input_usd_per_mtok is not None
            and settings.agent_price_output_usd_per_mtok is not None
        )
        warnings.append(
            "Sin tope de coste (AGENT_MAX_COST_USD_PER_ANALYSIS)"
            + ("" if priced else " ni precios por token (cost_usd = null)")
            + f": solo rige el tope de {settings.agent_max_tokens_per_analysis} tokens."
        )

    run = _Analysis(
        session=session,
        settings=settings,
        request=request,
        instrument=instrument,
        instrument_id=instrument_id,
        candles=candles,
        models=models,
        portfolio=portfolio,
        correlations=correlations,
        warnings=warnings,
    )
    return run.events()


# --- Ejecución --------------------------------------------------------------------------


class _Analysis:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        request: AnalyzeRequest,
        instrument: InstrumentSchema,
        instrument_id: int,
        candles: dict[Timeframe, list[CandleSchema]],
        models: dict[AgentRole, Any],
        portfolio: PortfolioState,
        correlations: dict[tuple[str, str], float],
        warnings: list[str],
    ) -> None:
        self.session = session
        self.settings = settings
        self.request = request
        self.instrument = instrument
        self.instrument_id = instrument_id
        self.candles = candles
        self.frames = {tf: candles_to_frame(c) for tf, c in candles.items()}
        self.models = models
        self.portfolio = portfolio
        self.correlations = correlations
        self.warnings = warnings
        self.analysis_id = uuid.uuid4()
        self.log = _log.bind(
            analysis_id=str(self.analysis_id), symbol=instrument.symbol, timeframe=request.timeframe
        )
        self._seq = 0
        self._tokens_used = 0
        self._latency_ms = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost: Decimal | None = Decimal(0)
        self._llm_steps = 0
        # Paso empezado y aún sin fila en `agent_analyses` (D109): (paso, entrada, inicio).
        self._open: tuple[AnalysisStep, dict[str, Any], float] | None = None

    # -- helpers --------------------------------------------------------------------------

    def _next(self) -> int:
        seq = self._seq
        self._seq += 1
        return seq

    def _redact(self, text: str) -> str:
        for key in (self.settings.anthropic_api_key, self.settings.gemini_api_key):
            if key is not None:
                secret = key.get_secret_value()
                if secret:
                    text = text.replace(secret, "[CLAVE OCULTA]")
        return text[:_MAX_ERROR_CHARS]

    def _error_text(self, step: AnalysisStep, exc: Exception) -> str:
        text = describe_step_error(
            step,
            exc,
            timeout_s=self.settings.agent_timeout_s,
            max_tokens=self.settings.agent_max_tokens_per_analysis,
        )
        return self._redact(text)

    def _frames_input(self, extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": self.instrument.symbol,
            "entry_timeframe": self.request.timeframe.value,
            "timeframes": {tf.value: _frame_meta(c) for tf, c in self.candles.items()},
            **extra,
        }

    def _deps(self) -> AgentDeps:
        # Una `AgentDeps` por agente: `kelly_calls` es estado por ejecución.
        return AgentDeps(
            instrument=self.instrument,
            candles=self.frames,
            settings=self.settings,
            portfolio=self.portfolio,
        )

    def _limits(self, step: AnalysisStep) -> UsageLimits:
        remaining = self.settings.agent_max_tokens_per_analysis - self._tokens_used
        if remaining <= 0:
            raise _StepError(
                f"Tope de tokens agotado antes de ejecutar {step.value}: consumo "
                f"{self._tokens_used} de AGENT_MAX_TOKENS_PER_ANALYSIS="
                f"{self.settings.agent_max_tokens_per_analysis}."
            )
        share = max(1, remaining * _TOKEN_WEIGHTS[step] // _PENDING_WEIGHT[step])
        return UsageLimits(request_limit=MAX_REQUESTS_PER_AGENT, total_tokens_limit=share)

    def _account(self, usage: StepUsage, *, llm: bool) -> None:
        self._tokens_used += usage.input_tokens + usage.output_tokens
        self._input_tokens += usage.input_tokens
        self._output_tokens += usage.output_tokens
        self._latency_ms += usage.latency_ms
        if llm:
            self._llm_steps += 1
            if usage.cost_usd is None or self._cost is None:
                self._cost = None
            else:
                self._cost += usage.cost_usd

    def _total_usage(self, extra: StepUsage | None = None, *, llm: bool = False) -> StepUsage:
        """Consumo acumulado; con `extra` suma además el de un paso aún no contabilizado."""
        inp, outp, lat = self._input_tokens, self._output_tokens, self._latency_ms
        cost, llm_steps = self._cost, self._llm_steps
        if extra is not None:
            inp += extra.input_tokens
            outp += extra.output_tokens
            lat += extra.latency_ms
            if llm:
                llm_steps += 1
                cost = None if cost is None or extra.cost_usd is None else cost + extra.cost_usd
        return StepUsage(
            model=None,
            input_tokens=inp,
            output_tokens=outp,
            cost_usd=cost if llm_steps else None,
            latency_ms=lat,
        )

    def _begin(self, step: AnalysisStep) -> None:
        """Marca el paso como empezado: desde aquí un fallo deja siempre una fila ERROR."""
        self._open = (step, {"symbol": self.instrument.symbol}, time.perf_counter())

    async def _persist(
        self,
        step: AnalysisStep,
        step_input: dict[str, Any],
        output: dict[str, Any] | None,
        trace: dict[str, Any] | None,
        usage: StepUsage,
        *,
        status: StepStatus,
        error: str | None = None,
        signal: TradeSignalSchema | None = None,
    ) -> None:
        """Inserta el paso (y la señal, si la hay) y confirma: una transacción por paso."""
        await steps_repo.insert_step(
            self.session,
            analysis_id=self.analysis_id,
            step=step,
            instrument_id=self.instrument_id,
            timeframe=self.request.timeframe,
            input=_json_safe(step_input),
            output=None if output is None else _json_safe(output),
            trace=None if trace is None else _json_safe(trace),
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            latency_ms=usage.latency_ms,
            status=status,
            error=error,
        )
        if signal is not None:
            await persist_signal(self.session, signal, self.instrument_id)
        await self.session.commit()
        self._open = None  # el paso ya tiene su fila (OK o ERROR)

    async def _fail(
        self,
        step: AnalysisStep,
        step_input: dict[str, Any],
        message: str,
        usage: StepUsage,
        trace: dict[str, Any] | None,
    ) -> NoReturn:
        await self._persist(
            step, step_input, None, trace, usage, status=StepStatus.ERROR, error=message
        )
        self._account(usage, llm=step in _ROLES)
        self.log.error("analysis_step_failed", step=step.value, error=message)
        raise _StepFailedError(step, message, usage)

    async def _execute[T](
        self,
        step: AnalysisStep,
        step_input: dict[str, Any],
        work: Callable[[], Awaitable[_Outcome[T]]],
        finalize: Callable[[_Outcome[T]], AnalysisCompleted | None] | None = None,
    ) -> _Done[T]:
        """Ejecuta `work`, construye los eventos de salida y confirma el paso.

        `finalize` (si el paso puede cerrar el análisis) construye el `AnalysisCompleted` ANTES
        del `commit`: si falla, no se confirma ni la señal ni el paso OK, y el paso queda en
        ``ERROR`` con el consumo conocido (D109).
        """
        started = time.perf_counter()
        if self._open is not None:
            self._open = (self._open[0], step_input, self._open[2])
        try:
            out = await work()
        except _StepError as exc:
            usage = exc.usage or StepUsage(latency_ms=round((time.perf_counter() - started) * 1000))
            await self._fail(step, step_input, self._redact(exc.message), usage, exc.trace)
        except Exception as exc:
            usage = StepUsage(latency_ms=round((time.perf_counter() - started) * 1000))
            await self._fail(step, step_input, self._error_text(step, exc), usage, None)
        if step in _ROLES and (message := self._cost_cap_message(step, out.usage)) is not None:
            await self._fail(step, step_input, message, out.usage, out.trace)
        mark = self._seq
        try:
            completed = self._completed(step, out)
            final = finalize(out) if finalize is not None else None
        except Exception as exc:
            self._seq = mark
            text = f"El paso {step.value} falló al construir su resultado: {_type_msg(exc)}"
            await self._fail(step, step_input, self._redact(text), out.usage, out.trace)
        try:
            await self._persist(
                step,
                step_input,
                out.output,
                out.trace,
                out.usage,
                status=StepStatus.OK,
                signal=out.signal,
            )
        except Exception as exc:
            self._seq = mark
            await self._rollback()
            text = f"El paso {step.value} falló al confirmar en la base de datos: {_type_msg(exc)}"
            await self._fail(step, step_input, self._redact(text), out.usage, out.trace)
        self._account(out.usage, llm=step in _ROLES)
        self.log.info(
            "analysis_step_completed",
            step=step.value,
            input_tokens=out.usage.input_tokens,
            output_tokens=out.usage.output_tokens,
            latency_ms=out.usage.latency_ms,
        )
        return _Done(out, completed, final)

    def _completed(self, step: AnalysisStep, out: _Outcome[Any]) -> StepCompleted:
        return StepCompleted(
            analysis_id=self.analysis_id,
            seq=self._next(),
            step=step,
            output=_json_safe(out.output),
            usage=out.usage,
        )

    def _cost_cap_message(self, step: AnalysisStep, usage: StepUsage) -> str | None:
        """Mensaje si el coste acumulado más el de este paso supera el tope (D95), si no `None`.

        El SDK no limita el coste: se comprueba al terminar cada paso LLM, antes de persistirlo
        como correcto (así una señal nunca se guarda tras exceder el tope).
        """
        cap = self.settings.agent_max_cost_usd_per_analysis
        if cap is None or self._cost is None or usage.cost_usd is None:
            return None
        total = self._cost + usage.cost_usd
        if total <= cap:
            return None
        return (
            f"Tope de coste excedido (AGENT_MAX_COST_USD_PER_ANALYSIS={cap}): coste acumulado "
            f"{total} USD tras {step.value}."
        )

    async def _run_llm[OutT](
        self, step: AnalysisStep, agent: Agent[AgentDeps, OutT], prompt: str, deps: AgentDeps
    ) -> AgentRun[OutT]:
        limits = self._limits(step)
        with agent.override(model=self.models[_ROLES[step]]):
            return await run_agent(agent, prompt, deps, limits, settings=self.settings)

    # -- pasos ----------------------------------------------------------------------------

    def _structure_prompt(self) -> str:
        tfs = ", ".join(tf.value for tf in self.candles)
        return (
            f"Analiza la estructura de mercado de {self.instrument.symbol}. Marco de entrada: "
            f"{self.request.timeframe.value}. Marcos disponibles: {tfs}. Usa "
            f"entry_timeframe = {self.request.timeframe.value}."
        )

    def _quant_prompt(self, structure: MarketStructureReport) -> str:
        return (
            f"Analiza el régimen cuantitativo de {self.instrument.symbol} en el marco de entrada "
            f"{self.request.timeframe.value} (usa timeframe = {self.request.timeframe.value}). "
            f"Contexto: el análisis de estructura concluyó sesgo HTF "
            f"{structure.htf_alignment.value}."
        )

    async def _work_structure(self, prompt: str) -> _Outcome[MarketStructureReport]:
        run = await self._run_llm(AnalysisStep.STRUCTURE, structure_agent, prompt, self._deps())
        report = run.output
        if report.entry_timeframe is not self.request.timeframe:
            raise _StepError(
                f"El informe de estructura usa entry_timeframe {report.entry_timeframe.value}, "
                f"se esperaba {self.request.timeframe.value}.",
                run.usage,
                run.trace,
            )
        return _Outcome(report, report.model_dump(mode="json"), run.usage, run.trace)

    async def _work_quant(self, prompt: str) -> _Outcome[QuantAlphaReport]:
        run = await self._run_llm(AnalysisStep.QUANT, quant_agent, prompt, self._deps())
        report = run.output
        if report.timeframe is not self.request.timeframe:
            raise _StepError(
                f"El informe cuantitativo usa timeframe {report.timeframe.value}, "
                f"se esperaba {self.request.timeframe.value}.",
                run.usage,
                run.trace,
            )
        return _Outcome(report, report.model_dump(mode="json"), run.usage, run.trace)

    def _proposal_params(self) -> ProposalParams:
        return ProposalParams(
            target_rr=self.settings.proposal_target_rr,
            sl_atr_buffer=self.settings.proposal_sl_atr_buffer,
        )

    async def _work_proposal(
        self, structure: MarketStructureReport, quant: QuantAlphaReport
    ) -> _Outcome[ProposedSignal | NoTradeReason]:
        started = time.perf_counter()
        tf = self.request.timeframe
        result = build_proposal(
            structure,
            quant,
            self.candles[tf][-1].close,
            _atr_decimal(self.frames[tf]),
            self.instrument,
            self._proposal_params(),
            fvgs=analyze_structure(self.frames[tf]).fvgs,
        )
        usage = StepUsage(latency_ms=round((time.perf_counter() - started) * 1000))
        if isinstance(result, NoTradeReason):
            output: dict[str, Any] = {"proposal": None, "no_trade_reason": result.reason}
        else:
            output = {"proposal": result.model_dump(mode="json"), "no_trade_reason": None}
        return _Outcome(result, output, usage)

    def _guards_input(self, proposal: ProposedSignal) -> dict[str, Any]:
        s = self.settings
        return {
            "proposal": proposal.model_dump(mode="json"),
            "portfolio": self.portfolio.model_dump(mode="json"),
            "correlations": [
                {"a": a, "b": b, "rho": rho} for (a, b), rho in sorted(self.correlations.items())
            ],
            "limits": {
                "risk_per_trade_pct": str(s.risk_per_trade_pct),
                "max_daily_loss_pct": str(s.max_daily_loss_pct),
                "min_rr": str(s.min_rr),
                "max_open_risk_pct": str(s.max_open_risk_pct),
                "max_correlated_risk_pct": str(s.max_correlated_risk_pct),
                "correlation_threshold": str(s.correlation_threshold),
            },
        }

    async def _work_guards(
        self, proposal: ProposedSignal, structure: MarketStructureReport, quant: QuantAlphaReport
    ) -> _Outcome[GuardDecision]:
        started = time.perf_counter()
        trade = ProposedTrade(
            symbol=proposal.symbol,
            direction=proposal.direction,
            entry=proposal.entry,
            stop_loss=proposal.stop_loss,
            take_profit=proposal.take_profit,
        )
        guard = evaluate_trade(
            trade, self.portfolio, self.correlations, self.instrument, self.settings
        )
        signal: TradeSignalSchema | None = None
        if not guard.approved:  # D94: el veto determinista manda; se persiste junto al paso
            signal = build_trade_signal(
                analysis_id=self.analysis_id,
                instrument=self.instrument,
                proposal=proposal,
                guard=guard,
                verdict=None,
                structure=structure,
                quant=quant,
            )
        usage = StepUsage(latency_ms=round((time.perf_counter() - started) * 1000))
        return _Outcome(guard, guard.model_dump(mode="json"), usage, signal=signal)

    async def _work_audit(
        self,
        proposal: ProposedSignal,
        guard: GuardDecision,
        structure: MarketStructureReport,
        quant: QuantAlphaReport,
    ) -> _Outcome[tuple[RiskVerdict, TradeSignalSchema]]:
        limits = self._limits(AnalysisStep.RISK_AUDIT)
        with risk_auditor_agent.override(model=self.models[AgentRole.AUDITOR]):
            verdict, run = await run_risk_audit(
                guard, proposal, self._deps(), settings=self.settings, limits=limits
            )
        if verdict is None or run is None:  # defensivo: solo ocurre con veto determinista
            raise _StepError("El auditor no se ejecutó con las guardas aprobadas.")
        signal = build_trade_signal(
            analysis_id=self.analysis_id,
            instrument=self.instrument,
            proposal=proposal,
            guard=guard,
            verdict=verdict,
            structure=structure,
            quant=quant,
        )
        output = {
            "risk_verdict": verdict.model_dump(mode="json"),
            "final_status": final_status(guard, verdict).value,
            "signal_id": str(signal.id),
        }
        return _Outcome((verdict, signal), output, run.usage, run.trace, signal)

    def _report(
        self,
        outcome: AnalysisOutcome,
        *,
        structure: MarketStructureReport | None = None,
        quant: QuantAlphaReport | None = None,
        proposal: ProposedSignal | None = None,
        guards: GuardDecision | None = None,
        verdict: RiskVerdict | None = None,
        signal: TradeSignalSchema | None = None,
        extra_warnings: list[str] | None = None,
        usage: StepUsage,
    ) -> AgentReportSchema:
        return AgentReportSchema(
            analysis_id=self.analysis_id,
            symbol=self.instrument.symbol,
            timeframe=self.request.timeframe,
            outcome=outcome,
            structure=structure,
            quant=quant,
            proposal=proposal,
            guards=guards,
            risk_verdict=verdict,
            signal=signal,
            usage=usage,
            warnings=[*self.warnings, *(extra_warnings or [])],
        )

    def _final(
        self, out: _Outcome[Any], outcome: AnalysisOutcome, *, llm: bool = False, **report: Any
    ) -> AnalysisCompleted:
        """`AnalysisCompleted` con el consumo total incluido el de `out` (aún sin contabilizar)."""
        return AnalysisCompleted(
            analysis_id=self.analysis_id,
            seq=self._next(),
            report=self._report(outcome, usage=self._total_usage(out.usage, llm=llm), **report),
        )

    async def _audit_open_step(self, message: str) -> tuple[AnalysisStep, StepUsage] | None:
        """Fila ERROR del paso empezado y sin fila (D109), en una transacción propia.

        Debe llamarse tras `rollback`. Si el INSERT de auditoría falla, solo se registra.
        """
        if self._open is None:
            return None
        step, step_input, began = self._open
        usage = StepUsage(latency_ms=round((time.perf_counter() - began) * 1000))
        try:
            await self._persist(
                step, step_input, None, None, usage, status=StepStatus.ERROR, error=message
            )
        except Exception as exc:
            self.log.error(
                "analysis_error_row_failed", step=step.value, error=self._redact(str(exc))
            )
            await self._rollback()
        self._open = None
        return step, usage

    # -- flujo ----------------------------------------------------------------------------

    async def events(self) -> AsyncGenerator[AnalysisEvent, None]:
        sid = self.analysis_id
        self.log.info("analysis_started", timeframes=[tf.value for tf in self.candles])
        try:
            yield AnalysisStarted(
                analysis_id=sid,
                seq=self._next(),
                symbol=self.instrument.symbol,
                timeframe=self.request.timeframe,
                timeframes=list(self.candles),
                started_at=datetime.now(UTC),
            )

            # 1. STRUCTURE (LLM)
            step = AnalysisStep.STRUCTURE
            self._begin(step)
            yield StepStarted(analysis_id=sid, seq=self._next(), step=step)
            prompt = self._structure_prompt()
            s_out = await self._execute(
                step, self._frames_input({"prompt": prompt}), lambda: self._work_structure(prompt)
            )
            yield s_out.completed
            structure = s_out.out.value

            # 2. QUANT (LLM)
            step = AnalysisStep.QUANT
            self._begin(step)
            yield StepStarted(analysis_id=sid, seq=self._next(), step=step)
            prompt = self._quant_prompt(structure)
            q_out = await self._execute(
                step, self._frames_input({"prompt": prompt}), lambda: self._work_quant(prompt)
            )
            yield q_out.completed
            quant = q_out.out.value

            # 3. PROPOSAL (código)
            step = AnalysisStep.PROPOSAL
            self._begin(step)
            yield StepStarted(analysis_id=sid, seq=self._next(), step=step)
            tf = self.request.timeframe
            p_input = self._frames_input(
                {
                    "playbook": quant.playbook.value,
                    "htf_alignment": structure.htf_alignment.value,
                    "zone_ts": structure.zone_ts.isoformat() if structure.zone_ts else None,
                    "invalidation_level": (
                        None
                        if structure.invalidation_level is None
                        else str(structure.invalidation_level)
                    ),
                    "zscore": quant.stats.zscore,
                    "last_close": str(self.candles[tf][-1].close),
                    "atr": str(_atr_decimal(self.frames[tf])),
                    "params": {
                        "target_rr": str(self.settings.proposal_target_rr),
                        "sl_atr_buffer": str(self.settings.proposal_sl_atr_buffer),
                    },
                }
            )

            def finalize_proposal(
                out: _Outcome[ProposedSignal | NoTradeReason],
            ) -> AnalysisCompleted | None:
                if not isinstance(out.value, NoTradeReason):
                    return None
                return self._final(
                    out,
                    AnalysisOutcome.NO_TRADE,
                    structure=structure,
                    quant=quant,
                    extra_warnings=[f"Sin operación: {out.value.reason}"],
                )

            p_out = await self._execute(
                step, p_input, lambda: self._work_proposal(structure, quant), finalize_proposal
            )
            yield p_out.completed
            if isinstance(p_out.out.value, NoTradeReason):
                self.log.info("analysis_no_trade", reason=p_out.out.value.reason)
                yield _required(p_out.final)
                return
            proposal = p_out.out.value

            # 4. GUARDS (código); el veto determinista cierra el análisis sin auditor (D94)
            step = AnalysisStep.GUARDS
            self._begin(step)
            yield StepStarted(analysis_id=sid, seq=self._next(), step=step)

            def finalize_guards(out: _Outcome[GuardDecision]) -> AnalysisCompleted | None:
                if out.value.approved:
                    return None
                return self._final(
                    out,
                    AnalysisOutcome.SIGNAL_REJECTED,
                    structure=structure,
                    quant=quant,
                    proposal=proposal,
                    guards=out.value,
                    signal=out.signal,
                )

            g_out = await self._execute(
                step,
                self._guards_input(proposal),
                lambda: self._work_guards(proposal, structure, quant),
                finalize_guards,
            )
            yield g_out.completed
            guard = g_out.out.value
            if not guard.approved:
                yield _required(g_out.final)
                return

            # 5. RISK_AUDIT (LLM)
            step = AnalysisStep.RISK_AUDIT
            self._begin(step)
            yield StepStarted(analysis_id=sid, seq=self._next(), step=step)

            def finalize_audit(
                out: _Outcome[tuple[RiskVerdict, TradeSignalSchema]],
            ) -> AnalysisCompleted | None:
                verdict, signal = out.value
                outcome = (
                    AnalysisOutcome.SIGNAL_APPROVED
                    if signal.status is SignalStatus.APPROVED
                    else AnalysisOutcome.SIGNAL_REJECTED
                )
                return self._final(
                    out,
                    outcome,
                    llm=True,
                    structure=structure,
                    quant=quant,
                    proposal=proposal,
                    guards=guard,
                    verdict=verdict,
                    signal=signal,
                )

            a_out = await self._execute(
                step,
                {"prompt": build_audit_prompt(guard, proposal), "symbol": self.instrument.symbol},
                lambda: self._work_audit(proposal, guard, structure, quant),
                finalize_audit,
            )
            yield a_out.completed
            _, signal = a_out.out.value
            final = _required(a_out.final)
            self.log.info(
                "analysis_completed", outcome=final.report.outcome.value, signal_id=str(signal.id)
            )
            yield final
        except _StepFailedError as failure:
            yield StepFailed(
                analysis_id=sid,
                seq=self._next(),
                step=failure.step,
                error=failure.message,
                usage=failure.usage,
            )
            yield AnalysisFailed(
                analysis_id=sid, seq=self._next(), error=failure.message, step=failure.step
            )
        except (asyncio.CancelledError, GeneratorExit):
            self.log.warning("analysis_cancelled")
            await self._rollback()
            raise
        except Exception as exc:
            message = self._redact(f"Error interno del análisis: {_type_msg(exc)}")
            self.log.error("analysis_internal_error", error=message)
            await self._rollback()
            failed = await self._audit_open_step(message)  # fila ERROR en transacción propia
            if failed is not None:
                yield StepFailed(
                    analysis_id=sid,
                    seq=self._next(),
                    step=failed[0],
                    error=message,
                    usage=failed[1],
                )
            yield AnalysisFailed(
                analysis_id=sid,
                seq=self._next(),
                error=message,
                step=failed[0] if failed is not None else None,
            )

    async def _rollback(self) -> None:
        try:
            await self.session.rollback()
        except Exception:
            self.log.warning("rollback_failed")
