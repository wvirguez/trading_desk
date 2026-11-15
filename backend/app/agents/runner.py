"""Ejecución de un agente con medición de latencia, tokens, coste y traza (D89, D95)."""

import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import TypeAdapter
from pydantic_ai import Agent, UsageLimits
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
)

from app.agents.prompts import PROMPT_VERSION
from app.core.config import Settings
from app.schemas.analysis import StepUsage

_MTOK = Decimal(1_000_000)
_JSON_DICT: TypeAdapter[Any] = TypeAdapter(Any)


class UsageLimitExceededError(Exception):
    """Se excedió un tope de uso; el mensaje nombra el tope y el consumo."""

    def __init__(self, message: str, *, limit: int | None, consumed: int | None) -> None:
        super().__init__(message)
        self.limit = limit
        self.consumed = consumed


@dataclass(frozen=True)
class AgentRun[OutputT]:
    output: OutputT
    usage: StepUsage
    trace: dict[str, Any]


def compute_cost(
    input_tokens: int,
    output_tokens: int,
    price_input_per_mtok: Decimal | None,
    price_output_per_mtok: Decimal | None,
) -> Decimal | None:
    """Coste en USD con precios por millón de tokens; `None` si falta algún precio (D95)."""
    if price_input_per_mtok is None or price_output_per_mtok is None:
        return None
    return (
        Decimal(input_tokens) * price_input_per_mtok
        + Decimal(output_tokens) * price_output_per_mtok
    ) / _MTOK


def _parse_limit_error(exc: UsageLimitExceeded) -> UsageLimitExceededError:
    text = str(exc)
    m = re.search(r"Exceeded the (\w+) of (\d+) \((\w+)=(\d+)\)", text)
    if m:
        name, limit, _, consumed = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        return UsageLimitExceededError(
            f"Se excedió el tope {name} = {limit} (consumo: {consumed}).",
            limit=limit,
            consumed=consumed,
        )
    m = re.search(r"Exceeded the (\w+) of (\d+)", text)
    if m:
        return UsageLimitExceededError(
            f"Se excedió el tope {m.group(1)} = {m.group(2)}.", limit=int(m.group(2)), consumed=None
        )
    return UsageLimitExceededError(f"Se excedió un tope de uso: {text}", limit=None, consumed=None)


def _system_prompt(messages: list[ModelMessage]) -> str:
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            parts.extend(p.content for p in msg.parts if isinstance(p, SystemPromptPart))
            if msg.instructions and msg.instructions not in parts:
                parts.append(msg.instructions)
    return "\n\n".join(dict.fromkeys(parts))


def _model_name(messages: list[ModelMessage], fallback: str | None) -> str | None:
    for msg in reversed(messages):
        if isinstance(msg, ModelResponse) and msg.model_name:
            return msg.model_name
    return fallback


async def run_agent[OutputT, DepsT](
    agent: Agent[DepsT, OutputT],
    prompt: str,
    deps: DepsT,
    limits: UsageLimits | None = None,
    *,
    settings: Settings,
) -> AgentRun[OutputT]:
    """Ejecuta el agente y devuelve `(output, StepUsage, trace)`.

    Convierte `UsageLimitExceeded` en `UsageLimitExceededError` (en español).
    La clave de API no forma parte de `deps` serializado ni de la traza.
    """
    started = time.perf_counter()
    try:
        result = await agent.run(
            prompt,
            deps=deps,
            usage_limits=limits,
            timeout=settings.agent_timeout_s,
        )
    except UsageLimitExceeded as exc:
        raise _parse_limit_error(exc) from exc
    latency_ms = round((time.perf_counter() - started) * 1000)

    usage = result.usage
    messages = result.all_messages()
    step = StepUsage(
        model=_model_name(messages, None),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=compute_cost(
            usage.input_tokens,
            usage.output_tokens,
            settings.agent_price_input_usd_per_mtok,
            settings.agent_price_output_usd_per_mtok,
        ),
        latency_ms=latency_ms,
    )
    trace: dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        "system_prompt": _system_prompt(messages),
        "messages": ModelMessagesTypeAdapter.dump_python(messages, mode="json"),
    }
    return AgentRun(output=result.output, usage=step, trace=trace)
