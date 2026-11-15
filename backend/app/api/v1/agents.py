"""`POST /api/v1/agents/analyze`: análisis multiagente en streaming SSE (D87).

Decisiones de implementación
----------------------------
- SSE con ``StreamingResponse`` (sin dependencias nuevas): un ``data: <json>\\n\\n`` por evento.
- Validación previa al *stream*: ``analyze`` es una corrutina que valida instrumento, datos y
  configuración en el ``await``; sus errores se traducen aquí a HTTP real (404/422/503) y solo
  después se abre el *stream*.
- Sesión: ``get_session`` es una dependencia con ``yield``; desde FastAPI 0.118 su salida corre
  DESPUÉS de enviar la respuesta completa (alcance ``request`` por defecto), así que la sesión
  sigue viva durante todo el *stream* y no hace falta abrirla dentro del generador.
- Desconexión: si el cliente corta, Starlette cancela la tarea; ``sse_body`` cierra el generador
  del orquestador (``aclose``), que hace *rollback*. Lo confirmado por paso permanece (D87).
- D98 (OpenAPI): el esquema de ``AnalysisEvent`` se publica con ``responses={200: {"model":
  AnalysisEventEnvelope}}`` (D108: envoltorio nombrado de la unión ``AnalysisEvent``; cada
  ``data:`` sigue siendo un evento) y ``response_class=EventStreamResponse``
  (``media_type="text/event-stream"``).
  FastAPI usa el ``media_type`` de la ``response_class`` para el contenido de las respuestas
  adicionales, así que ``openapi.json`` declara 200 como ``text/event-stream`` con el esquema
  discriminado y todos los componentes (``AgentReportSchema``, ``TradeSignalSchema``...) con su
  nomenclatura habitual, sin hook sobre ``app.openapi`` ni esquemas escritos a mano; el generador
  de tipos TS los recibe como cualquier otro componente. ``AnalyzeRequest`` sale del cuerpo.
"""

from collections.abc import AsyncGenerator, AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import (
    AgentsNotConfiguredError,
    ModelFactory,
    default_model_factory,
    key_variable,
)
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.schemas.analysis import AnalysisEvent, AnalysisEventEnvelope, AnalyzeRequest
from app.services.analysis import (
    InstrumentNotFoundError,
    InsufficientDataError,
    analyze,
)

router = APIRouter(prefix="/agents", tags=["agents"])


def not_configured_detail(variable: str) -> str:
    return f"El análisis con agentes no está configurado: falta {variable}."


class EventStreamResponse(StreamingResponse):
    """`StreamingResponse` con `media_type` propio para que OpenAPI declare `text/event-stream`."""

    media_type = "text/event-stream"


def get_model_factory(settings: Annotated[Settings, Depends(get_settings)]) -> ModelFactory:
    """Dependencia sustituible en tests: fábrica de modelos por rol."""
    return default_model_factory(settings)


async def sse_body(stream: AsyncGenerator[AnalysisEvent, None]) -> AsyncIterator[bytes]:
    """Serializa cada evento como `data: <json>` y cierra el orquestador al terminar o cortar."""
    try:
        async for event in stream:
            yield f"data: {event.model_dump_json()}\n\n".encode()
    finally:
        await stream.aclose()


@router.post(
    "/analyze",
    response_class=EventStreamResponse,
    responses={
        status.HTTP_200_OK: {
            "model": AnalysisEventEnvelope,
            "description": (
                "Flujo `text/event-stream`: un evento `data: <json>` por `AnalysisEvent`. "
                "Los fallos durante el análisis llegan como `analysis_failed` (HTTP 200)."
            ),
        },
        status.HTTP_404_NOT_FOUND: {"description": "Instrumento desconocido"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Cuerpo inválido o datos insuficientes"
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": (
                "Agentes no configurados (falta la clave del proveedor activo o AGENT_MODEL)"
            )
        },
    },
)
async def post_analyze(
    body: AnalyzeRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    model_factory: Annotated[ModelFactory, Depends(get_model_factory)],
) -> StreamingResponse:
    try:
        stream = await analyze(session, body, settings, model_factory)
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InsufficientDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except AgentsNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=not_configured_detail(exc.variable or key_variable(settings)),
        ) from exc
    return EventStreamResponse(
        sse_body(stream),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
