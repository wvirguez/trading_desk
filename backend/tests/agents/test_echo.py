import pytest
from pydantic import SecretStr
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.exceptions import UnexpectedModelBehavior, UserError
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from app.agents.echo import EchoReport, echo_agent
from app.agents.models import AgentRole, build_model
from app.core.config import Settings


async def test_echo_agent_with_test_model_returns_typed_output() -> None:
    with echo_agent.override(model=TestModel()):
        result = await echo_agent.run("hola")
    assert isinstance(result.output, EchoReport)


async def test_echo_agent_function_model_valid_output() -> None:
    def respond(_: list[object], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"message": "ok", "length": 2})]
        )

    with echo_agent.override(model=FunctionModel(respond)):  # type: ignore[arg-type]
        result = await echo_agent.run("ok")
    assert result.output == EchoReport(message="ok", length=2)


async def test_invalid_output_is_retried_and_fails_after_max() -> None:
    calls = 0

    def respond(_: list[object], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"bad": 1})])

    with (
        echo_agent.override(model=FunctionModel(respond)),  # type: ignore[arg-type]
        pytest.raises(UnexpectedModelBehavior),
    ):
        await echo_agent.run("x")
    assert calls == 3  # intento inicial + 2 reintentos de validación


async def test_agent_without_override_fails_instead_of_reaching_network() -> None:
    # D84: ALLOW_MODEL_REQUESTS=False o falta de clave; en ambos casos no hay red.
    with pytest.raises((RuntimeError, UserError)):
        await echo_agent.run("x")


async def test_real_model_without_override_is_blocked_by_allow_model_requests() -> None:
    settings = Settings(_env_file=None, anthropic_api_key=SecretStr("sk-x"))  # type: ignore[call-arg]
    model = build_model(settings, AgentRole.STRUCTURE)
    with pytest.raises(RuntimeError, match="not allowed"):
        await echo_agent.run("x", model=model)
