"""Traducción de errores del SDK a español técnico (D113), sin base de datos."""

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelHTTPError,
    RunTimedOut,
    UnexpectedModelBehavior,
)

from app.agents.runner import UsageLimitExceededError
from app.schemas.enums import AnalysisStep
from app.services.analysis import describe_step_error

STEP = AnalysisStep.QUANT


def describe(exc: Exception) -> str:
    return describe_step_error(STEP, exc, timeout_s=120, max_tokens=60000)


def test_tope_de_uso_conserva_su_mensaje_y_nombra_el_tope() -> None:
    exc = UsageLimitExceededError(
        "Se excedió el tope total_tokens_limit = 100", limit=100, consumed=250
    )
    text = describe(exc)
    assert text.startswith("Se excedió el tope total_tokens_limit = 100")
    assert "AGENT_MAX_TOKENS_PER_ANALYSIS=60000" in text


def test_timeout_nombra_la_variable_y_el_tipo() -> None:
    text = describe(RunTimedOut("The agent run timed out."))
    assert text == (
        "El paso QUANT superó el tiempo máximo por ejecución de agente "
        "(AGENT_TIMEOUT_S=120 s): RunTimedOut."
    )
    assert "TimeoutError" in describe(TimeoutError())


def test_reintentos_agotados_incluye_el_ultimo_rechazo_del_validador() -> None:
    exc = UnexpectedModelBehavior("Exceeded maximum output retries (2)")
    exc.__cause__ = ModelRetry("nivel 9.99 no existe en get_structure")
    text = describe(exc)
    assert "no devolvió una salida válida tras agotar los reintentos" in text
    assert "UnexpectedModelBehavior: Exceeded maximum output retries (2)" in text
    assert "Último rechazo: nivel 9.99 no existe en get_structure" in text


def test_comportamiento_inesperado_sin_reintentos() -> None:
    text = describe(UnexpectedModelBehavior("Received empty model response"))
    assert text == (
        "El paso QUANT falló: comportamiento inesperado del modelo "
        "(UnexpectedModelBehavior): Received empty model response"
    )


def test_error_http_y_error_de_api_del_proveedor() -> None:
    http = describe(ModelHTTPError(429, "claude-x", body={"error": "rate_limited"}))
    assert "error del proveedor del modelo (ModelHTTPError, HTTP 429, modelo claude-x)" in http
    assert "rate_limited" in http
    api = describe(ModelAPIError("gemini-x", "connection reset"))
    assert (
        "error de comunicación con el proveedor del modelo (ModelAPIError, modelo gemini-x)" in api
    )
    assert api.endswith("connection reset")


def test_el_cuerpo_largo_del_proveedor_se_acota() -> None:
    text = describe(ModelHTTPError(500, "m", body="x" * 5000))
    assert len(text) < 700


@pytest.mark.parametrize("exc", [RuntimeError("boom"), ValueError("v")])
def test_errores_desconocidos_conservan_tipo_y_mensaje(exc: Exception) -> None:
    assert describe(exc) == f"El paso QUANT falló: {type(exc).__name__}: {exc}"
