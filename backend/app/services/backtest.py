"""Servicio de backtest: lee velas de `ohlcv_bars`, ejecuta el motor y registra la corrida (D64).

Orden de validación: instrumento -> datos -> ejecución. Confirma la transacción (como el
servicio de ingesta).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.quant.backtest import config_hash, periods_per_year, run_backtest, to_metrics_schema
from app.quant.data import candles_to_frame
from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as ohlcv_repo
from app.repositories import strategies as strategies_repo
from app.schemas.enums import Provider, SessionType
from app.schemas.quant import BacktestConfig, BacktestMetricsSchema

STRATEGY_NAME = "zscore_mean_reversion"


class InstrumentNotFoundError(Exception):
    def __init__(self, symbol: str) -> None:
        super().__init__(f"Instrumento desconocido: {symbol}")
        self.symbol = symbol


class InsufficientDataError(Exception):
    def __init__(self, symbol: str, timeframe: str, n_bars: int, required: int) -> None:
        super().__init__(
            f"Datos insuficientes para {symbol} {timeframe}: {n_bars} velas, "
            f"se necesitan al menos {required}."
        )
        self.n_bars = n_bars
        self.required = required


class TooManyBarsError(Exception):
    def __init__(self, symbol: str, timeframe: str, n_bars: int, maximum: int) -> None:
        super().__init__(
            f"Datos excesivos para {symbol} {timeframe}: demasiadas velas: {n_bars} o más, "
            f"máximo {maximum}. Acota con start/end."
        )
        self.n_bars = n_bars
        self.maximum = maximum


async def run_backtest_for_config(
    session: AsyncSession, config: BacktestConfig, settings: Settings
) -> BacktestMetricsSchema:
    """Ejecuta el backtest de `config` sobre los datos guardados y persiste la corrida."""
    instrument = await instruments_repo.get_by_symbol(session, config.symbol)
    if instrument is None:
        raise InstrumentNotFoundError(config.symbol)

    max_bars = settings.backtest_max_bars
    candles = await ohlcv_repo.fetch_range(
        session,
        instrument.id,
        config.timeframe,
        instrument.symbol,
        config.start,
        config.end,
        max_bars + 1,
    )
    if len(candles) > max_bars:
        # `fetch_range` recorta a `max_bars + 1`: el total real puede ser mayor.
        raise TooManyBarsError(config.symbol, config.timeframe.value, len(candles), max_bars)
    required = config.zscore_window + 2
    if len(candles) < required:
        raise InsufficientDataError(config.symbol, config.timeframe.value, len(candles), required)

    frame = candles_to_frame(candles)
    ppy = periods_per_year(config.timeframe, SessionType(instrument.session))
    result = run_backtest(frame, config, ppy)

    warnings = [
        "Backtest sin costes ni slippage: las métricas son optimistas respecto a la operativa real."
    ]
    if Provider(instrument.provider) is Provider.YAHOO:
        warnings.append("Datos provisionales de Yahoo Finance, no oficiales.")
    if result.n_trades == 0:
        warnings.append("Sin operaciones en el periodo: las métricas son 0.")

    data_from, data_to = candles[0].ts, candles[-1].ts
    draft = to_metrics_schema(result, config, uuid.uuid4(), warnings)
    row = await strategies_repo.insert_strategy(
        session,
        name=STRATEGY_NAME,
        instrument_id=instrument.id,
        timeframe=config.timeframe,
        params=config.model_dump(mode="json"),
        metrics=draft.model_dump(mode="json", exclude={"equity_curve", "config", "strategy_id"}),
        config_hash=config_hash(config, data_from, data_to),
        data_from=data_from,
        data_to=data_to,
    )
    strategy_id = row.id  # antes del commit: la sesión expira los atributos al confirmar
    await session.commit()
    return draft.model_copy(update={"strategy_id": strategy_id})
