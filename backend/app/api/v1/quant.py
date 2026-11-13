"""`POST /api/v1/quant/backtest`: backtest de la estrategia de referencia."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.schemas.quant import BacktestConfig, BacktestMetricsSchema
from app.services.backtest import (
    InstrumentNotFoundError,
    InsufficientDataError,
    TooManyBarsError,
    run_backtest_for_config,
)

router = APIRouter(prefix="/quant", tags=["quant"])


@router.post(
    "/backtest",
    response_model=BacktestMetricsSchema,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Instrumento desconocido"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Configuración inválida o datos insuficientes/excesivos"
        },
    },
)
async def post_backtest(
    config: BacktestConfig,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BacktestMetricsSchema:
    try:
        return await run_backtest_for_config(session, config, settings)
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (InsufficientDataError, TooManyBarsError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
