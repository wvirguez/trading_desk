"""Esquemas de señales de trading. Precios y dinero en Decimal."""

from datetime import datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.enums import (
    AssetClass,
    Direction,
    RegimeLabel,
    SignalStatus,
    Timeframe,
    VetoReason,
)
from app.schemas.risk import PositionSizeResult

# Prefijo obligatorio en `rationale` cuando el auditor rechaza una señal sin motivos
# deterministas (D94). El orquestador lo escribe; el esquema lo exige.
AUDITOR_REJECTION_MARKER = "Rechazo del auditor:"

# El texto libre del LLM que entra en `rationale` va etiquetado y acotado (D112).
UNVERIFIED_LABEL = "NO VERIFICADO"
MAX_MODEL_TEXT_CHARS = 400


def model_text(text: str, limit: int = MAX_MODEL_TEXT_CHARS) -> str:
    """Texto del modelo con espacios normalizados y acotado a `limit` caracteres (con «…»)."""
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


_SIGNAL_CONFIG = ConfigDict(frozen=True, extra="forbid")


def _validar_niveles(
    direction: Direction, entry: Decimal, stop_loss: Decimal, take_profit: Decimal
) -> None:
    for nombre, valor in (("entry", entry), ("stop_loss", stop_loss), ("take_profit", take_profit)):
        if not valor.is_finite() or valor <= 0:
            raise ValueError(f"{nombre} debe ser un decimal finito mayor que 0 (recibido {valor})")
    if direction is Direction.LONG:
        if not stop_loss < entry < take_profit:
            raise ValueError(
                "En LONG se exige stop_loss < entry < take_profit "
                f"(stop_loss={stop_loss}, entry={entry}, take_profit={take_profit})"
            )
    elif not take_profit < entry < stop_loss:
        raise ValueError(
            "En SHORT se exige take_profit < entry < stop_loss "
            f"(stop_loss={stop_loss}, entry={entry}, take_profit={take_profit})"
        )


class ProposedSignal(BaseModel):
    """Propuesta determinista (sin tamaño ni estado). Niveles coherentes con la dirección."""

    model_config = _SIGNAL_CONFIG

    symbol: str
    timeframe: Timeframe
    direction: Direction
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    rr: Decimal
    source: str  # explica de dónde sale cada nivel

    @model_validator(mode="after")
    def _niveles_coherentes(self) -> Self:
        _validar_niveles(self.direction, self.entry, self.stop_loss, self.take_profit)
        if not self.rr.is_finite() or self.rr <= 0:
            raise ValueError(f"rr debe ser un decimal finito mayor que 0 (recibido {self.rr})")
        return self


class TradeSignalSchema(BaseModel):
    """Señal canónica persistida.

    Invariantes:
    - LONG: stop_loss < entry < take_profit; SHORT: take_profit < entry < stop_loss.
    - APPROVED: `size` presente y `veto_reasons` vacío.
    - REJECTED: `veto_reasons` no vacío (veto determinista) O, si está vacío, `rationale`
      debe contener `AUDITOR_REJECTION_MARKER` (rechazo del auditor, que no genera
      motivos `VetoReason`).
    - PENDING y EXECUTED no imponen reglas adicionales.
    """

    model_config = _SIGNAL_CONFIG

    id: UUID
    analysis_id: UUID
    symbol: str
    asset_class: AssetClass
    timeframe: Timeframe
    direction: Direction
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    rr: Decimal
    size: PositionSizeResult | None = None
    status: SignalStatus
    regime: RegimeLabel
    rationale: str
    veto_reasons: list[VetoReason]
    created_at: datetime

    @model_validator(mode="after")
    def _invariantes(self) -> Self:
        _validar_niveles(self.direction, self.entry, self.stop_loss, self.take_profit)
        if self.status is SignalStatus.APPROVED:
            if self.size is None:
                raise ValueError("Una señal APPROVED requiere size")
            if self.veto_reasons:
                raise ValueError("Una señal APPROVED no puede tener veto_reasons")
        elif (
            self.status is SignalStatus.REJECTED
            and not self.veto_reasons
            and AUDITOR_REJECTION_MARKER not in self.rationale
        ):
            raise ValueError(
                "Una señal REJECTED requiere veto_reasons o un rechazo del auditor "
                f"registrado en rationale (con el prefijo '{AUDITOR_REJECTION_MARKER}')"
            )
        return self
