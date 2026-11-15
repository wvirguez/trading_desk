"""Construcción del modelo de lenguaje a partir de la configuración (D83).

No realiza ninguna llamada de red: solo instancia el cliente.
"""

from collections.abc import Callable
from enum import StrEnum

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider

from app.core.config import Settings


class AgentRole(StrEnum):
    STRUCTURE = "STRUCTURE"
    QUANT = "QUANT"
    AUDITOR = "AUDITOR"


class AgentsNotConfiguredError(Exception):
    """Los agentes no pueden ejecutarse porque falta configuración (la API responde 503).

    `variable` es la variable de entorno que falta (p. ej. `GEMINI_API_KEY`), si se conoce.
    """

    def __init__(self, message: str, variable: str | None = None) -> None:
        super().__init__(message)
        self.variable = variable


_KEY_VARIABLE = {"anthropic": "ANTHROPIC_API_KEY", "google": "GEMINI_API_KEY"}


def key_variable(settings: Settings) -> str:
    """Nombre de la variable con la clave del proveedor activo."""
    return _KEY_VARIABLE[settings.agent_provider]


def build_model(settings: Settings, role: AgentRole) -> Model:
    """Devuelve el modelo del rol según `AGENT_PROVIDER`.

    El auditor usa `AGENT_AUDITOR_MODEL` si está definido. Solo instancia el cliente (sin red).
    """
    variable = key_variable(settings)
    secret = (
        settings.anthropic_api_key if variable == "ANTHROPIC_API_KEY" else settings.gemini_api_key
    )
    if secret is None or not secret.get_secret_value().strip():
        raise AgentsNotConfiguredError(
            f"{variable} no está configurada: los agentes de análisis están deshabilitados. "
            "Defínela en el entorno (backend/.env) para habilitarlos.",
            variable,
        )
    key = secret.get_secret_value()
    if settings.agent_provider == "google" and "agent_model" not in settings.model_fields_set:
        raise AgentsNotConfiguredError(
            "AGENT_MODEL no está definido: con AGENT_PROVIDER=google debe indicarse un modelo "
            "Gemini explícito (el valor por defecto solo es válido para anthropic).",
            "AGENT_MODEL",
        )
    name = settings.agent_model
    if role is AgentRole.AUDITOR and settings.agent_auditor_model:
        name = settings.agent_auditor_model
    if settings.agent_provider == "google":
        return GoogleModel(name, provider=GoogleProvider(api_key=key))
    return AnthropicModel(name, provider=AnthropicProvider(api_key=key))


# Fábrica de modelos por rol: el orquestador la recibe como parámetro para poder sustituirla en
# tests y en la API (dependencia `get_model_factory`) sin red. Lanza `AgentsNotConfiguredError`
# si no hay modelo disponible.
ModelFactory = Callable[[AgentRole], Model]


def default_model_factory(settings: Settings) -> ModelFactory:
    """Fábrica de producción: `build_model`; sin clave lanza `AgentsNotConfiguredError`."""

    def factory(role: AgentRole) -> Model:
        return build_model(settings, role)

    return factory
