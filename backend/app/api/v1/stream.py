"""WebSocket `/api/v1/ws/stream/{symbol}`: stream de ticks y alertas de señal.

Decisiones de implementación
----------------------------
- WebSocket nativo de FastAPI/Starlette con `{symbol:path}` para admitir símbolos
  con `/` (p. ej. `BTC/USDT` codificado como `BTC%2FUSDT`).
- Parámetro de query `tf` obligatorio (`Timeframe`).
- Dependencia `get_tick_source` sustituible en tests (Protocol `TickSource`).
- El sondeo usa `StreamPoller` del servicio de stream; intervalo y reloj inyectables
  vía `Settings.ws_poll_interval_s`.
- Cierre con código 1008 y motivo en español para símbolo desconocido o `tf` inválido.
- Al cerrar el cliente, la tarea del sondeo se cancela (sin tareas colgadas).
- `StreamEventEnvelope` se publica en `components` de OpenAPI mediante una
  respuesta documental (D121): se declara en `responses` del endpoint con
  `model=StreamEventEnvelope` y `media_type="application/json"` solo para
  que el generador de OpenAPI incluya el esquema en `components/schemas`.
  El WebSocket real envía JSON plano (un evento por mensaje), no el envoltorio.
- Errores de dominio → `HTTPException` con `detail` en español.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session, get_sessionmaker
from app.repositories import instruments as instruments_repo
from app.schemas.enums import Timeframe
from app.schemas.stream import (
    StreamEventEnvelope,
)
from app.services.stream import DbTickSource, StreamPoller, TickSource

router = APIRouter(prefix="/ws", tags=["stream"])


def get_tick_source(session: Annotated[AsyncSession, Depends(get_session)]) -> TickSource:
    """Dependencia sustituible en tests: fuente de ticks (DB por defecto)."""
    return DbTickSource(session)


class _RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@router.websocket("/stream/{symbol:path}")
async def ws_stream(
    websocket: WebSocket,
    symbol: str,
    tf: Annotated[Timeframe, Query(alias="tf")],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    tick_source: Annotated[TickSource, Depends(get_tick_source)],
) -> None:
    """WebSocket de stream de precio y alertas de señal.

    - `symbol`: símbolo canónico (p. ej. `BTC/USDT`), codificado en la URL.
    - `tf`: timeframe obligatorio (`5m`, `15m`, `1h`, `4h`, `1d`).

    Envía mensajes JSON `StreamEvent` (uno por mensaje):
    - `TickUpdateEvent` (type="tick"): último cierre ingerido, `provisional=true`.
    - `SignalAlertEvent` (type="signal_alert"): nueva señal `APPROVED`.
    - `StreamErrorEvent` (type="error"): error de la fuente, sondeo continúa.

    Cierra con código 1008 si:
    - El símbolo no existe en la BD.
    - El `tf` no es un `Timeframe` válido (validación de FastAPI).
    """
    # Validar símbolo antes de aceptar la conexión
    instrument = await instruments_repo.get_by_symbol(session, symbol)
    if instrument is None:
        reason = f"Instrumento desconocido: {symbol}"
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
        return

    await websocket.accept()

    since = datetime.now(UTC)
    interval = timedelta(seconds=settings.ws_poll_interval_s)

    poller = StreamPoller(
        source=tick_source,
        symbol=symbol,
        timeframe=tf,
        interval=interval,
        clock=_RealClock(),
        since=since,
        session_factory=get_sessionmaker(),
    )

    try:
        async for event in poller:
            await websocket.send_json(event.model_dump(mode="json"))
    except Exception:  # noqa: S110
        # Cliente desconectado u otro error: terminar limpiamente
        pass
    finally:
        await websocket.close()


# Endpoint documental para que OpenAPI incluya StreamEventEnvelope en components (D121)
@router.get(
    "/stream/_openapi_docs",
    response_model=StreamEventEnvelope,
    responses={
        200: {
            "model": StreamEventEnvelope,
            "description": "Documental: esquema de eventos de WebSocket (no es un endpoint real).",
        }
    },
)
async def _stream_openapi_docs() -> JSONResponse:
    """Endpoint falso solo para que OpenAPI registre StreamEventEnvelope en components."""
    return JSONResponse(content={}, status_code=200)
