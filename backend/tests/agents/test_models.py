import pytest
from pydantic import SecretStr
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel

from app.agents.models import AgentRole, AgentsNotConfiguredError, build_model
from app.core.config import Settings

SECRET = "sk-ant-super-secreta-123"  # noqa: S105


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def test_without_key_raises_not_configured_in_spanish() -> None:
    with pytest.raises(AgentsNotConfiguredError, match="ANTHROPIC_API_KEY"):
        build_model(_settings(anthropic_api_key=None), AgentRole.STRUCTURE)


def test_not_configured_message_is_spanish() -> None:
    with pytest.raises(AgentsNotConfiguredError) as exc:
        build_model(_settings(anthropic_api_key=None), AgentRole.QUANT)
    assert "no está configurada" in str(exc.value)


def test_with_key_returns_configured_model_without_network() -> None:
    settings = _settings(anthropic_api_key=SecretStr(SECRET), agent_model="claude-test-1")
    model = build_model(settings, AgentRole.STRUCTURE)
    assert model.model_name == "claude-test-1"
    assert build_model(settings, AgentRole.QUANT).model_name == "claude-test-1"


def test_auditor_uses_auditor_model_when_set() -> None:
    settings = _settings(
        anthropic_api_key=SecretStr(SECRET),
        agent_model="claude-test-1",
        agent_auditor_model="claude-test-aud",
    )
    assert build_model(settings, AgentRole.AUDITOR).model_name == "claude-test-aud"
    assert build_model(settings, AgentRole.STRUCTURE).model_name == "claude-test-1"


def test_auditor_falls_back_to_agent_model() -> None:
    settings = _settings(anthropic_api_key=SecretStr(SECRET), agent_model="claude-test-1")
    assert build_model(settings, AgentRole.AUDITOR).model_name == "claude-test-1"


def test_key_is_not_in_repr() -> None:
    settings = _settings(anthropic_api_key=SecretStr(SECRET))
    model = build_model(settings, AgentRole.STRUCTURE)
    assert SECRET not in repr(model)
    assert SECRET not in str(model)
    assert SECRET not in repr(settings)


GEMINI_SECRET = "AIza-gemini-super-secreta-456"  # noqa: S105


def _google(**kw: object) -> Settings:
    base: dict[str, object] = {
        "agent_provider": "google",
        "gemini_api_key": SecretStr(GEMINI_SECRET),
        "agent_model": "gemini-3.8-flash",
    }
    return _settings(**(base | kw))


def test_anthropic_provider_builds_anthropic_model() -> None:
    settings = _settings(anthropic_api_key=SecretStr(SECRET))
    assert isinstance(build_model(settings, AgentRole.QUANT), AnthropicModel)


def test_anthropic_ignores_gemini_key_and_names_its_own_variable() -> None:
    settings = _settings(gemini_api_key=SecretStr(GEMINI_SECRET))
    with pytest.raises(AgentsNotConfiguredError, match="ANTHROPIC_API_KEY") as exc:
        build_model(settings, AgentRole.STRUCTURE)
    assert exc.value.variable == "ANTHROPIC_API_KEY"


@pytest.mark.parametrize("role", list(AgentRole))
def test_google_provider_builds_google_model_without_network(role: AgentRole) -> None:
    model = build_model(_google(), role)
    assert isinstance(model, GoogleModel)
    assert model.model_name == "gemini-3.8-flash"


def test_google_auditor_uses_auditor_model() -> None:
    settings = _google(agent_auditor_model="gemini-3.5-flash-lite")
    assert build_model(settings, AgentRole.AUDITOR).model_name == "gemini-3.5-flash-lite"
    assert build_model(settings, AgentRole.QUANT).model_name == "gemini-3.8-flash"


def test_google_without_key_names_gemini_variable() -> None:
    settings = _google(gemini_api_key=None, anthropic_api_key=SecretStr(SECRET))
    with pytest.raises(AgentsNotConfiguredError, match="GEMINI_API_KEY") as exc:
        build_model(settings, AgentRole.STRUCTURE)
    assert "no está configurada" in str(exc.value)
    assert "ANTHROPIC_API_KEY" not in str(exc.value)
    assert exc.value.variable == "GEMINI_API_KEY"


def test_google_requires_explicit_model() -> None:
    settings = _settings(agent_provider="google", gemini_api_key=SecretStr(GEMINI_SECRET))
    with pytest.raises(AgentsNotConfiguredError, match="AGENT_MODEL") as exc:
        build_model(settings, AgentRole.STRUCTURE)
    assert exc.value.variable == "AGENT_MODEL"
    assert GEMINI_SECRET not in str(exc.value)


def test_gemini_key_is_not_in_repr() -> None:
    settings = _google()
    model = build_model(settings, AgentRole.STRUCTURE)
    assert GEMINI_SECRET not in repr(model)
    assert GEMINI_SECRET not in str(model)
    assert GEMINI_SECRET not in repr(settings)
