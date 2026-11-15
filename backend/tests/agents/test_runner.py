import json
from decimal import Decimal

import pytest
from pydantic_ai import ModelResponse, RequestUsage, TextPart, ToolCallPart, UsageLimits
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from app.agents.echo import EchoReport, echo_agent
from app.agents.prompts import ECHO_PROMPT, PROMPT_VERSION
from app.agents.runner import UsageLimitExceededError, compute_cost, run_agent
from app.core.config import Settings
from app.schemas.analysis import StepUsage


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def _fixed_usage_model(inp: int, out: int) -> FunctionModel:
    def respond(_: list[object], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"message": "a", "length": 1})],
            usage=RequestUsage(input_tokens=inp, output_tokens=out),
        )

    return FunctionModel(respond)  # type: ignore[arg-type]


def test_compute_cost_with_prices() -> None:
    cost = compute_cost(1_000_000, 500_000, Decimal("3"), Decimal("15"))
    assert cost == Decimal("10.5")
    assert isinstance(cost, Decimal)


def test_compute_cost_small_exact() -> None:
    assert compute_cost(1000, 2000, Decimal("3"), Decimal("15")) == Decimal("0.033")


@pytest.mark.parametrize(
    ("p_in", "p_out"),
    [(None, None), (Decimal("3"), None), (None, Decimal("15"))],
)
def test_compute_cost_none_without_prices(p_in: Decimal | None, p_out: Decimal | None) -> None:
    assert compute_cost(10, 10, p_in, p_out) is None


async def test_run_agent_returns_output_usage_and_trace() -> None:
    settings = _settings(
        agent_price_input_usd_per_mtok=Decimal("3"),
        agent_price_output_usd_per_mtok=Decimal("15"),
    )
    with echo_agent.override(model=_fixed_usage_model(1000, 2000)):
        run = await run_agent(echo_agent, "hola", None, settings=settings)
    assert run.output == EchoReport(message="a", length=1)
    assert isinstance(run.usage, StepUsage)
    assert run.usage.input_tokens == 1000
    assert run.usage.output_tokens == 2000
    assert run.usage.cost_usd == Decimal("0.033")
    assert run.usage.latency_ms >= 0
    assert run.usage.model is not None


async def test_run_agent_cost_null_without_prices() -> None:
    with echo_agent.override(model=_fixed_usage_model(10, 10)):
        run = await run_agent(echo_agent, "hola", None, settings=_settings())
    assert run.usage.cost_usd is None


async def test_trace_is_json_serializable_with_prompt_and_messages() -> None:
    with echo_agent.override(model=TestModel()):
        run = await run_agent(echo_agent, "hola mundo", None, settings=_settings())
    trace = json.loads(json.dumps(run.trace))
    assert trace["prompt_version"] == PROMPT_VERSION
    assert trace["system_prompt"] == ECHO_PROMPT
    kinds = [m["kind"] for m in trace["messages"]]
    assert kinds[0] == "request" and "response" in kinds
    assert "hola mundo" in json.dumps(trace["messages"])


async def test_trace_includes_tool_calls_and_never_the_key() -> None:
    secret = "sk-ant-nunca-en-traza"  # noqa: S105
    with echo_agent.override(model=TestModel()):
        run = await run_agent(
            echo_agent, "hola", None, settings=_settings(anthropic_api_key=secret)
        )
    dumped = json.dumps(run.trace)
    assert "tool-call" in dumped
    assert secret not in dumped


async def test_usage_limit_exceeded_names_limit_and_consumption() -> None:
    limits = UsageLimits(total_tokens_limit=100)
    with echo_agent.override(model=_fixed_usage_model(500, 600)):
        with pytest.raises(UsageLimitExceededError) as exc:
            await run_agent(echo_agent, "x", None, settings=_settings(), limits=limits)
    msg = str(exc.value)
    assert "100" in msg and "1100" in msg
    assert exc.value.limit == 100
    assert exc.value.consumed == 1100


async def test_text_response_model_is_not_an_output() -> None:
    # Un modelo que responde texto plano no cumple la salida tipada: falla, no se acepta.
    def respond(_: list[object], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("hola")])

    with (
        echo_agent.override(model=FunctionModel(respond)),  # type: ignore[arg-type]
        pytest.raises(Exception),  # noqa: B017
    ):
        await run_agent(echo_agent, "x", None, settings=_settings())


async def test_run_agent_with_google_settings_extracts_usage_model_and_hides_key() -> None:
    """El runner es agnóstico al proveedor: tokens, modelo y coste salen igual con Gemini."""
    secret = "AIza-gemini-super-secreta-456"  # noqa: S105
    settings = _settings(
        agent_provider="google",
        gemini_api_key=secret,
        agent_model="gemini-3.8-flash",
        agent_price_input_usd_per_mtok=Decimal("3"),
        agent_price_output_usd_per_mtok=Decimal("15"),
    )

    def respond(_: list[object], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"message": "a", "length": 1})],
            usage=RequestUsage(input_tokens=1000, output_tokens=2000),
            model_name="gemini-3.8-flash",
        )

    model = FunctionModel(respond, model_name="gemini-3.8-flash")  # type: ignore[arg-type]
    with echo_agent.override(model=model):
        run = await run_agent(echo_agent, "hola", None, settings=settings)

    assert run.usage.model == "gemini-3.8-flash"
    assert run.usage.input_tokens == 1000
    assert run.usage.output_tokens == 2000
    assert run.usage.cost_usd == Decimal("0.033")
    assert secret not in json.dumps(run.trace, default=str)
