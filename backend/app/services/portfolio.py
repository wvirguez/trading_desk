"""Estado de cartera simulado y correlación real para las guardas (D90).

Hasta el paper trading (4.6) no hay PnL real: `equity = day_start_equity = ACCOUNT_EQUITY_USD`,
`realized_pnl_today = 0` y las posiciones abiertas son las señales `EXECUTED` (vacío por ahora).
La matriz de correlación sí es real: cierres de los instrumentos en el marco de entrada.
No hace `commit`.
"""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.quant.data import candles_to_frame
from app.repositories import ohlcv as ohlcv_repo
from app.repositories import trade_signals as signals_repo
from app.risk.correlation import correlation_matrix
from app.schemas.enums import Timeframe
from app.schemas.risk import PortfolioState

SIMULATED_PORTFOLIO_WARNING = "Estado de cartera simulado: sin PnL real hasta el paper trading"


async def load_portfolio_state(
    session: AsyncSession, settings: Settings
) -> tuple[PortfolioState, list[str]]:
    """Estado de cartera (D90) y los avisos que debe propagar el análisis."""
    open_positions = await signals_repo.list_executed(session)
    state = PortfolioState(
        equity=settings.account_equity_usd,
        day_start_equity=settings.account_equity_usd,
        realized_pnl_today=Decimal(0),
        open_positions=open_positions,
    )
    return state, [SIMULATED_PORTFOLIO_WARNING]


async def load_correlation_matrix(
    session: AsyncSession,
    instruments: Sequence[tuple[int, str]],
    timeframe: Timeframe,
    window: int,
) -> dict[tuple[str, str], float]:
    """Correlación de log-retornos de los cierres de `(id, símbolo)` en `timeframe`.

    Pide `window + 1` cierres por instrumento (= `window` retornos). Los instrumentos sin
    velas se omiten: sus pares no figuran y las guardas los tratan como correlación 1.0 (D63).
    """
    closes = {}
    for instrument_id, symbol in instruments:
        candles = await ohlcv_repo.fetch_latest(
            session, instrument_id, timeframe, window + 1, symbol
        )
        if len(candles) >= 2:
            closes[symbol] = candles_to_frame(candles)
    return correlation_matrix(closes, window)
