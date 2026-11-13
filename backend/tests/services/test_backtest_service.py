"""Tests `db` del servicio de backtest, con velas sintéticas insertadas en `ohlcv_bars`."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.strategy import Strategy
from app.quant.backtest import periods_per_year, run_backtest, to_metrics_schema
from app.quant.data import candles_to_frame
from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as ohlcv_repo
from app.schemas.candle import CandleSchema
from app.schemas.enums import SessionType, Timeframe
from app.schemas.quant import BacktestConfig
from app.services.backtest import (
    InstrumentNotFoundError,
    InsufficientDataError,
    TooManyBarsError,
    run_backtest_for_config,
)
from tests.quant.synthetic import mean_reverting

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("use_test_db")]

T0 = datetime(2026, 1, 1, tzinfo=UTC)


async def seed(
    session: AsyncSession, symbol: str, n: int, tf: Timeframe = Timeframe.H1
) -> list[CandleSchema]:
    row = await instruments_repo.get_by_symbol(session, symbol)
    assert row is not None
    prices = mean_reverting(n, seed=7)
    step = tf.duration
    candles = [
        CandleSchema(
            symbol=symbol,
            timeframe=tf,
            ts=T0 + i * step,
            open=Decimal(str(round(p, 4))),
            high=Decimal(str(round(p + 0.5, 4))),
            low=Decimal(str(round(p - 0.5, 4))),
            close=Decimal(str(round(p, 4))),
            volume=Decimal(10),
        )
        for i, p in enumerate(prices)
    ]
    await ohlcv_repo.upsert_candles(session, row.id, candles)
    await session.commit()
    return candles


def cfg(symbol: str = "EUR/USD", **kw: object) -> BacktestConfig:
    base: dict[str, object] = {"symbol": symbol, "timeframe": Timeframe.H1, "zscore_window": 20}
    return BacktestConfig.model_validate(base | kw)


async def count(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(Strategy))).scalar_one())


async def test_coincide_con_el_motor_directo(db_session: AsyncSession) -> None:
    candles = await seed(db_session, "EUR/USD", 300)
    config = cfg()

    got = await run_backtest_for_config(db_session, config, get_settings())

    direct = run_backtest(
        candles_to_frame(candles), config, periods_per_year(Timeframe.H1, SessionType.FX_24_5)
    )
    expected = to_metrics_schema(direct, config, got.strategy_id, got.warnings)
    assert got == expected
    assert got.n_bars == 300


async def test_persiste_una_fila_con_el_id_devuelto(db_session: AsyncSession) -> None:
    candles = await seed(db_session, "EUR/USD", 300)

    got = await run_backtest_for_config(db_session, cfg(), get_settings())

    rows = (await db_session.execute(select(Strategy))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.id == got.strategy_id
    assert row.name == "zscore_mean_reversion"
    assert row.params == cfg().model_dump(mode="json")
    assert "equity_curve" not in row.metrics
    assert row.metrics["n_bars"] == 300
    assert row.data_from == candles[0].ts
    assert row.data_to == candles[-1].ts


async def test_reintento_da_mismo_hash_y_metricas(db_session: AsyncSession) -> None:
    await seed(db_session, "EUR/USD", 300)

    a = await run_backtest_for_config(db_session, cfg(), get_settings())
    b = await run_backtest_for_config(db_session, cfg(), get_settings())

    assert a.strategy_id != b.strategy_id
    assert a.model_copy(update={"strategy_id": b.strategy_id}) == b
    rows = (await db_session.execute(select(Strategy))).scalars().all()
    assert len(rows) == 2
    assert rows[0].config_hash == rows[1].config_hash


async def test_simbolo_desconocido(db_session: AsyncSession) -> None:
    with pytest.raises(InstrumentNotFoundError, match="Instrumento desconocido: XYZ"):
        await run_backtest_for_config(db_session, cfg("XYZ"), get_settings())
    assert await count(db_session) == 0


async def test_datos_insuficientes(db_session: AsyncSession) -> None:
    await seed(db_session, "EUR/USD", 21)

    with pytest.raises(InsufficientDataError) as info:
        await run_backtest_for_config(db_session, cfg(), get_settings())

    assert str(info.value) == (
        "Datos insuficientes para EUR/USD 1h: 21 velas, se necesitan al menos 22."
    )
    assert await count(db_session) == 0


async def test_exceso_de_velas(db_session: AsyncSession) -> None:
    await seed(db_session, "EUR/USD", 150)
    settings = Settings(_env_file=None, backtest_max_bars=100)  # type: ignore[call-arg]

    with pytest.raises(TooManyBarsError, match=r"demasiadas velas: 101 o más, máximo 100"):
        await run_backtest_for_config(db_session, cfg(), settings)
    assert await count(db_session) == 0


async def test_warnings_costes_y_yahoo(db_session: AsyncSession) -> None:
    await seed(db_session, "EUR/USD", 300)

    got = await run_backtest_for_config(db_session, cfg(), get_settings())

    assert any("sin costes ni slippage" in w for w in got.warnings)
    assert any("Yahoo Finance" in w for w in got.warnings)


async def test_warning_sin_operaciones(db_session: AsyncSession) -> None:
    await seed(db_session, "EUR/USD", 300)

    got = await run_backtest_for_config(db_session, cfg(entry_z=50.0), get_settings())

    assert got.n_trades == 0
    assert any("Sin operaciones" in w for w in got.warnings)


async def test_sin_aviso_yahoo_en_cripto(db_session: AsyncSession) -> None:
    await seed(db_session, "BTC/USDT", 300)

    got = await run_backtest_for_config(db_session, cfg("BTC/USDT"), get_settings())

    assert not any("Yahoo" in w for w in got.warnings)


async def test_filtros_start_end(db_session: AsyncSession) -> None:
    candles = await seed(db_session, "EUR/USD", 300)
    start, end = T0 + timedelta(hours=50), T0 + timedelta(hours=250)

    got = await run_backtest_for_config(db_session, cfg(start=start, end=end), get_settings())

    assert got.n_bars == 200  # start inclusivo, end exclusivo
    assert got.equity_curve[0].ts == candles[50].ts
    assert got.equity_curve[-1].ts == candles[249].ts
    row = (await db_session.execute(select(Strategy))).scalar_one()
    assert row.data_from == candles[50].ts
    assert row.data_to == candles[249].ts
