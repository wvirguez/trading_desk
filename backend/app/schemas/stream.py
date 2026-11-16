"""Esquemas de eventos de stream (WebSocket)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, TypeAdapter

from app.schemas.enums import Timeframe
from app.schemas.signals import TradeSignalSchema

_STREAM_CONFIG = ConfigDict(frozen=True, extra="forbid")


class TickUpdateEvent(BaseModel):
    """Actualización de precio (último cierre ingerido, no tiempo real)."""

    model_config = _STREAM_CONFIG

    type: Literal["tick"]
    symbol: str
    timeframe: Timeframe
    price: Annotated[str, Field(pattern=r"^\d+(\.\d+)?$")]
    provisional: Literal[True]


class SignalAlertEvent(BaseModel):
    """Alerta de nueva señal APPROVED."""

    model_config = _STREAM_CONFIG

    type: Literal["signal"]
    signal: TradeSignalSchema


class StreamErrorEvent(BaseModel):
    """Error del stream con mensaje en español."""

    model_config = _STREAM_CONFIG

    type: Literal["error"]
    message: str


StreamEvent = Annotated[
    TickUpdateEvent | SignalAlertEvent | StreamErrorEvent,
    Field(discriminator="type"),
]

StreamEventAdapter = TypeAdapter(StreamEvent)


class StreamEventEnvelope(RootModel[StreamEvent]):
    """Envoltorio para el envoltorio raíz de eventos de stream."""

    model_config = ConfigDict(frozen=True)
