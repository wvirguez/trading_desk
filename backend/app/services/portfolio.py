"""Estado de cartera real y correlación real para las guardas (D90, D138).

El estado se deriva de `paper_orders`, sin columnas de saldo (D138):
- `equity = ACCOUNT_EQUITY_USD + Σ realized_pnl` de todas las órdenes cerradas; el PnL no
  realizado de las abiertas no entra.
- `realized_pnl_today = Σ realized_pnl` de las órdenes con `closed_at` en el día UTC actual.
- `day_start_equity = equity - realized_pnl_today`.
- `open_positions` = órdenes `PENDING_FILL`/`OPEN` con su `risk_amount`.
No hace `commit`.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.quant.data import candles_to_frame
from app.repositories import ohlcv as ohlcv_repo
from app.repositories import paper_orders as orders_repo
from app.repositories import trade_signals as signals_repo
from app.risk.correlation import correlation_matrix
from app.schemas.enums import Timeframe
from app.schemas.risk import PortfolioState


async def load_portfolio_state(
    session: AsyncSession, settings: Settings, now: datetime | None = None
) -> tuple[PortfolioState, list[str]]:
    """Estado de cartera (D138) y los avisos que debe propagar el análisis (hoy, ninguno).

    `now` inyecta el reloj (por defecto, ahora en UTC) para delimitar el día UTC.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    total_pnl = await orders_repo.sum_realized_pnl(session)
    pnl_today = await orders_repo.sum_realized_pnl_between(
        session, day_start, day_start + timedelta(days=1)
    )
    equity = settings.account_equity_usd + total_pnl
    state = PortfolioState(
        equity=equity,
        day_start_equity=equity - pnl_today,
        realized_pnl_today=pnl_today,
        open_positions=await signals_repo.list_executed(session),
    )
    return state, []


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
