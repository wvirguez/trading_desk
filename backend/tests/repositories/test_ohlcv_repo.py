"""Tests `db` del repositorio de velas."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ohlcv_bar import OhlcvBar
from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as repo
from app.schemas.candle import CandleSchema
from app.schemas.enums import Timeframe

pytestmark = pytest.mark.db

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _candles(n: int, close: str = "105") -> list[CandleSchema]:
    return [
        CandleSchema(
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            ts=T0 + timedelta(hours=i),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal(close),
            volume=Decimal("12.5"),
        )
        for i in range(n)
    ]


async def _count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(OhlcvBar))).scalar_one()


async def _btc_id(session: AsyncSession) -> int:
    row = await instruments_repo.get_by_symbol(session, "BTC/USDT")
    assert row is not None
    return row.id


async def test_upsert_idempotente(db_session: AsyncSession) -> None:
    iid = await _btc_id(db_session)
    candles = _candles(5)
    assert await repo.upsert_candles(db_session, iid, candles) == 5
    assert await repo.upsert_candles(db_session, iid, candles) == 0
    assert await _count(db_session) == 5


async def test_vela_corregida_se_actualiza(db_session: AsyncSession) -> None:
    iid = await _btc_id(db_session)
    await repo.upsert_candles(db_session, iid, _candles(3))
    assert await repo.upsert_candles(db_session, iid, _candles(3, close="106")) == 3
    assert await _count(db_session) == 3
    last = (await repo.fetch_latest(db_session, iid, Timeframe.H1, 1, "BTC/USDT"))[0]
    assert last.close == Decimal("106")


async def test_lotes_de_mil(db_session: AsyncSession) -> None:
    iid = await _btc_id(db_session)
    assert await repo.upsert_candles(db_session, iid, _candles(2500)) == 2500
    assert await _count(db_session) == 2500


async def test_latest_ts_y_fetch_latest(db_session: AsyncSession) -> None:
    iid = await _btc_id(db_session)
    assert await repo.latest_ts(db_session, iid, Timeframe.H1) is None
    await repo.upsert_candles(db_session, iid, _candles(10))
    assert await repo.latest_ts(db_session, iid, Timeframe.H1) == T0 + timedelta(hours=9)
    assert await repo.latest_ts(db_session, iid, Timeframe.D1) is None
    latest = await repo.fetch_latest(db_session, iid, Timeframe.H1, 3, "BTC/USDT")
    assert [c.ts for c in latest] == [T0 + timedelta(hours=h) for h in (7, 8, 9)]
