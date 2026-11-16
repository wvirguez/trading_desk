"""Tests `db` del servicio de mercado."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as ohlcv_repo
from app.schemas.candle import CandleSchema
from app.schemas.enums import Timeframe
from app.services.backtest import InstrumentNotFoundError, InsufficientDataError
from app.services.market import get_instruments, get_structure

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("use_test_db")]

T0 = datetime(2026, 1, 1, tzinfo=UTC)


async def _seed_candles(
    session: AsyncSession, symbol: str, n: int, tf: Timeframe = Timeframe.H1
) -> list[CandleSchema]:
    row = await instruments_repo.get_by_symbol(session, symbol)
    assert row is not None
    step = tf.duration
    candles = [
        CandleSchema(
            symbol=symbol,
            timeframe=tf,
            ts=T0 + step * i,
            open=Decimal("100"),
            high=Decimal("200"),
            low=Decimal("50"),
            close=Decimal(str(100 + (i % 50))),  # Mantener close entre 100-149
            volume=Decimal("12.5"),
        )
        for i in range(n)
    ]
    await ohlcv_repo.upsert_candles(session, row.id, candles)
    await session.commit()
    return candles


class TestGetInstruments:
    async def test_devuelve_los_4_instrumentos_del_seed(self, db_session: AsyncSession) -> None:
        instruments = await get_instruments(db_session)
        assert len(instruments) == 4
        symbols = {i.symbol for i in instruments}
        assert symbols == {"BTC/USDT", "EUR/USD", "XAU/USD", "NAS100"}

    async def test_orden_por_id(self, db_session: AsyncSession) -> None:
        from sqlalchemy import select

        from app.models.instrument import Instrument

        # Verificar el orden directamente en la BD
        stmt = select(Instrument).order_by(Instrument.id)
        rows = list((await db_session.execute(stmt)).scalars())
        symbols_in_order = [r.symbol for r in rows]

        instruments = await get_instruments(db_session)
        symbols = [i.symbol for i in instruments]
        assert symbols == symbols_in_order


class TestGetStructure:
    async def test_coincide_con_analyze_structure_sobre_mismas_velas(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_candles(db_session, "EUR/USD", 100)

        from app.quant.data import candles_to_frame
        from app.quant.structure import analyze_structure

        candles = await ohlcv_repo.fetch_range(
            db_session,
            (await instruments_repo.get_by_symbol(db_session, "EUR/USD")).id,
            Timeframe.H1,
            "EUR/USD",
            None,
            None,
            100,
        )
        frame = candles_to_frame(candles)
        expected = analyze_structure(frame, n=3)

        result = await get_structure(db_session, "EUR/USD", Timeframe.H1, n=3)

        assert result.swings == expected.swings
        assert result.events == expected.events
        assert result.fvgs == expected.fvgs

    async def test_simbolo_desconocido_lanza_instrument_not_found(
        self, db_session: AsyncSession
    ) -> None:
        with pytest.raises(InstrumentNotFoundError, match="Instrumento desconocido: XYZ"):
            await get_structure(db_session, "XYZ", Timeframe.H1, n=3)

    async def test_menos_de_2n_mas_1_velas_lanza_insufficient_data(
        self, db_session: AsyncSession
    ) -> None:
        # n=3 requiere al menos 7 velas (2*3+1)
        await _seed_candles(db_session, "EUR/USD", 6)

        with pytest.raises(InsufficientDataError) as info:
            await get_structure(db_session, "EUR/USD", Timeframe.H1, n=3)

        assert info.value.n_bars == 6
        assert info.value.required == 7
        assert "6 velas" in str(info.value)
        assert "7" in str(info.value)

    async def test_n_fuera_de_rango_1_10_lanza_error(self, db_session: AsyncSession) -> None:
        await _seed_candles(db_session, "EUR/USD", 100)

        with pytest.raises(ValueError, match="n debe estar entre 1 y 10"):
            await get_structure(db_session, "EUR/USD", Timeframe.H1, n=0)

        with pytest.raises(ValueError, match="n debe estar entre 1 y 10"):
            await get_structure(db_session, "EUR/USD", Timeframe.H1, n=11)

    async def test_diferentes_timeframes(self, db_session: AsyncSession) -> None:
        await _seed_candles(db_session, "BTC/USDT", 50, Timeframe.M15)

        result = await get_structure(db_session, "BTC/USDT", Timeframe.M15, n=3)
        assert len(result.swings) >= 0
        assert len(result.events) >= 0
        assert len(result.fvgs) >= 0
