"""Servicio de ingesta OHLCV: backfill e incremental por instrumento y timeframe."""

from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.market_data.base import MarketDataAdapter, NoticeReporter
from app.models.instrument import Instrument
from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as ohlcv_repo
from app.schemas.enums import Provider, Timeframe

_DAYS_PER_YEAR = 365


class IngestResult(BaseModel):
    """Resumen de una ingesta: velas recibidas, filas escritas y rango recibido."""

    symbol: str
    timeframe: Timeframe
    fetched: int
    written: int
    first_ts: datetime | None
    last_ts: datetime | None
    notices: list[str] = []  # avisos del proveedor (D30, D49), en español


def default_since(
    tf: Timeframe,
    now: datetime,
    settings: Settings | None = None,
    provider: Provider | None = None,
) -> datetime:
    """Inicio del backfill por defecto según el horizonte configurado (D17).

    Para instrumentos de `YAHOO` se usan los horizontes de ese proveedor (D30, D38).
    """
    cfg = settings or get_settings()
    if provider is Provider.YAHOO:
        yahoo_days = {
            Timeframe.M5: cfg.backfill_days_5m_yahoo,
            Timeframe.M15: cfg.backfill_days_15m_yahoo,
            Timeframe.H1: cfg.backfill_days_1h_yahoo,
            Timeframe.H4: cfg.backfill_days_4h_yahoo,
            Timeframe.D1: cfg.backfill_years_1d * _DAYS_PER_YEAR,
        }[tf]
        return now - timedelta(days=yahoo_days)
    days = {
        Timeframe.M5: cfg.backfill_days_5m,
        Timeframe.M15: cfg.backfill_days_15m,
        Timeframe.H1: cfg.backfill_years_1h * _DAYS_PER_YEAR,
        Timeframe.H4: cfg.backfill_years_4h * _DAYS_PER_YEAR,
        Timeframe.D1: cfg.backfill_years_1d * _DAYS_PER_YEAR,
    }[tf]
    return now - timedelta(days=days)


async def _ingest(
    session: AsyncSession,
    adapter: MarketDataAdapter,
    instrument: Instrument,
    tf: Timeframe,
    start: datetime,
    end: datetime,
) -> IngestResult:
    candles = await adapter.fetch_ohlcv(instruments_repo.to_schema(instrument), tf, start, end)
    notices = [n.message for n in adapter.notices] if isinstance(adapter, NoticeReporter) else []
    written = await ohlcv_repo.upsert_candles(session, instrument.id, candles)
    await session.commit()
    return IngestResult(
        symbol=instrument.symbol,
        timeframe=tf,
        fetched=len(candles),
        written=written,
        first_ts=candles[0].ts if candles else None,
        last_ts=candles[-1].ts if candles else None,
        notices=notices,
    )


async def backfill(
    session: AsyncSession,
    adapter: MarketDataAdapter,
    instrument: Instrument,
    tf: Timeframe,
    since: datetime,
    until: datetime | None = None,
    *,
    now: datetime,
) -> IngestResult:
    """Descarga `[since, until)` (por defecto hasta `now`) y la guarda con upsert idempotente."""
    return await _ingest(session, adapter, instrument, tf, since, until or now)


async def incremental(
    session: AsyncSession,
    adapter: MarketDataAdapter,
    instrument: Instrument,
    tf: Timeframe,
    *,
    now: datetime,
    settings: Settings | None = None,
) -> IngestResult:
    """Parte del último `ts` guardado, re-pidiendo esa vela (D16); sin datos, hace backfill."""
    last = await ohlcv_repo.latest_ts(session, instrument.id, tf)
    if last is None:
        return await backfill(
            session,
            adapter,
            instrument,
            tf,
            default_since(tf, now, settings, Provider(instrument.provider)),
            now=now,
        )
    return await _ingest(session, adapter, instrument, tf, last, now)
