"""Acceso a `strategies`: registro de backtests ejecutados (D64)."""

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy import Strategy
from app.schemas.enums import Timeframe


async def insert_strategy(
    session: AsyncSession,
    *,
    name: str,
    instrument_id: int,
    timeframe: Timeframe,
    params: dict[str, Any],
    metrics: dict[str, Any],
    config_hash: str,
    data_from: datetime,
    data_to: datetime,
) -> Strategy:
    """Inserta una fila y la devuelve con `id` y `created_at` ya cargados.

    Hace `flush` (para obtener los valores del servidor) pero no `commit`: lo decide quien
    llama (D21). `params` y `metrics` deben ser serializables a JSON (sin `Decimal`/`datetime`).
    """
    strategy = Strategy(
        name=name,
        instrument_id=instrument_id,
        timeframe=timeframe.value,
        params=params,
        metrics=metrics,
        config_hash=config_hash,
        data_from=data_from,
        data_to=data_to,
    )
    session.add(strategy)
    await session.flush()
    await session.refresh(strategy)
    return strategy
