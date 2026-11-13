"""Adaptador de Yahoo Finance (proveedor provisional, D28-D37, D48-D49). Es el único módulo que toca
`yfinance` y `pandas`: el resto del código solo ve `CandleSchema`.

Aviso de historia recortada (D30)
---------------------------------
Yahoo solo sirve unos días de historia en los intervalos cortos (5m/15m: 59 días; 1h y 4h: 729
días) y rechaza con 0 filas las peticiones que los superan. Cuando `start` queda más atrás
del límite, el adaptador recorta la petición a lo disponible y lo anota en el atributo
`history_notice` (un `HistoryNotice`, o `None` si se entregó todo lo pedido).

Bloques 4h parciales (D31, D49)
-------------------------------
El 4h se construye desde 1h y un bloque cerrado se emite con las velas de 1h que existan
(al menos una). Si alguno tuvo menos de 4, se anota en `partial_notice`
(`PartialBlocksNotice`, o `None`).

Respuesta vacía (D43)
---------------------
Una respuesta sin filas no es un error (un incremental en fin de semana la recibe de forma
legítima): se devuelve `[]` y se anota `empty_notice` (`EmptyResponseNotice`). Red, formato y
columnas ausentes siguen siendo `MarketDataError`.

Todos los atributos de aviso se reinician en cada `fetch_ohlcv`; la propiedad `notices` los junta
(el servicio la lee tras la llamada) y cada aviso trae su `message` en español. No se usa
excepción ni log: la llamada devuelve las velas disponibles y los avisos viajan aparte.

Combinaciones no soportadas (D48)
---------------------------------
`_UNSUPPORTED` lista, por ticker, los timeframes que Yahoo no puede dar con la alineación
que exige `CandleSchema`. Pedirlos lanza `UnsupportedTimeframeError` antes de llamar al
descargador. Hoy: `^NDX` en 1h y 4h (Yahoo abre sus velas de 1h a :30 UTC). `^NDX` solo
está disponible en 5m, 15m y 1d.
"""

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import yfinance as yf
from pydantic import ValidationError

from app.market_data.base import (
    MarketDataError,
    NoticeLike,
    UnsupportedTimeframeError,
    drop_open_candle,
    utcnow,
)
from app.schemas.candle import CandleSchema
from app.schemas.enums import Provider, Timeframe
from app.schemas.instrument import InstrumentSchema

# Descargador: (ticker, intervalo de Yahoo, inicio, fin) -> DataFrame OHLCV. Síncrono.
Downloader = Callable[[str, str, datetime, datetime], pd.DataFrame]

_INTERVALS: dict[Timeframe, str] = {
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.H1: "1h",
    Timeframe.H4: "1h",  # D31: 4h se construye desde 1h
    Timeframe.D1: "1d",
}

# Historia máxima que acepta Yahoo (D30, medida el 2026-11-13).
_MAX_HISTORY: dict[Timeframe, timedelta] = {
    Timeframe.M5: timedelta(days=59),
    Timeframe.M15: timedelta(days=59),
    Timeframe.H1: timedelta(days=729),
    Timeframe.H4: timedelta(days=729),
}

# D48: (ticker -> timeframes que no se pueden pedir a Yahoo) con el motivo mostrado al usuario.
_UNSUPPORTED: dict[str, tuple[frozenset[Timeframe], str]] = {
    "^NDX": (
        frozenset({Timeframe.H1, Timeframe.H4}),
        "Yahoo entrega las velas de 1h de ^NDX alineadas a :30, que no se admiten; "
        "NAS100 solo está disponible en 5m, 15m y 1d con este proveedor",
    ),
}

# El servicio calcula `start` unos instantes antes que el reloj del adaptador.
_NOTICE_TOLERANCE = timedelta(hours=1)
_COLUMNS = ("Open", "High", "Low", "Close", "Volume")
_PRICES = ("Open", "High", "Low", "Close")
_H4_PARTS = 4


@dataclass(frozen=True)
class HistoryNotice:
    """Se devolvió menos historia de la pedida (D30)."""

    timeframe: Timeframe
    requested_start: datetime
    available_start: datetime

    @property
    def message(self) -> str:
        days = (self.available_start.date() - self.requested_start.date()).days
        limit = _MAX_HISTORY[self.timeframe].days
        return (
            f"Yahoo solo ofrece {limit} días de historia en {self.timeframe.value}: se pidió "
            f"desde {self.requested_start:%Y-%m-%d} y se recibe desde "
            f"{self.available_start:%Y-%m-%d} ({days} días menos)."
        )


@dataclass(frozen=True)
class PartialBlocksNotice:
    """Bloques de 4h construidos con menos de 4 velas de 1h (D31, D49)."""

    partial: int
    total: int

    @property
    def message(self) -> str:
        return (
            f"4h: {self.partial} de {self.total} bloques se construyeron con menos de "
            f"{_H4_PARTS} velas de 1h."
        )


@dataclass(frozen=True)
class EmptyResponseNotice:
    """Yahoo respondió sin velas (D43): mercado cerrado, sin datos nuevos o rechazo del rango."""

    ticker: str
    timeframe: Timeframe
    start: datetime
    end: datetime

    @property
    def message(self) -> str:
        return (
            f"Yahoo no devolvió velas para {self.ticker} {self.timeframe.value} entre "
            f"{self.start:%Y-%m-%d %H:%M} y {self.end:%Y-%m-%d %H:%M} UTC (mercado cerrado o "
            "sin datos nuevos; un bloqueo de Yahoo se ve igual)."
        )


def yahoo_downloader(ticker: str, interval: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Descargador real (bloqueante): precios sin ajustar, sin dividendos ni splits."""
    frame: pd.DataFrame = yf.Ticker(ticker).history(
        start=start,
        end=end,
        interval=interval,
        auto_adjust=False,
        actions=False,
        raise_errors=True,
    )
    return frame


class YahooAdapter:
    """Velas OHLCV de Yahoo Finance. Sin credenciales; el descargador es inyectable (D34, D35).

    `history_notice`, `partial_notice` y `empty_notice` describen la última llamada; `notices`
    los junta (véase el docstring del módulo).
    """

    provider = Provider.YAHOO

    def __init__(self, downloader: Downloader, now: Callable[[], datetime] = utcnow) -> None:
        self._downloader = downloader
        self._now = now
        self.history_notice: HistoryNotice | None = None
        self.partial_notice: PartialBlocksNotice | None = None
        self.empty_notice: EmptyResponseNotice | None = None

    @property
    def notices(self) -> list[NoticeLike]:
        found: list[NoticeLike] = []
        if self.history_notice is not None:
            found.append(self.history_notice)
        if self.partial_notice is not None:
            found.append(self.partial_notice)
        if self.empty_notice is not None:
            found.append(self.empty_notice)
        return found

    async def fetch_ohlcv(
        self,
        instrument: InstrumentSchema,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[CandleSchema]:
        if instrument.provider is not Provider.YAHOO:
            raise MarketDataError(
                f"El instrumento {instrument.symbol} es de {instrument.provider.value}, no de YAHOO"
            )
        unsupported = _UNSUPPORTED.get(instrument.provider_symbol)
        if unsupported is not None and timeframe in unsupported[0]:
            raise UnsupportedTimeframeError(
                f"{instrument.symbol} {timeframe.value} no soportado: {unsupported[1]}"
            )
        now = self._now()
        self.history_notice = None
        self.partial_notice = None
        self.empty_notice = None
        eff_start = self._clamp_start(timeframe, start, now)
        if eff_start >= end:
            return []

        # 4h: se pide 1h con el rango ampliado a bloques completos de 4h (D31).
        req_start, req_end = eff_start, end
        if timeframe is Timeframe.H4:
            req_start = timeframe.floor(eff_start)
            req_end = timeframe.floor(end - timedelta(microseconds=1)) + timeframe.duration
        frame = await self._download(instrument, timeframe, req_start, req_end)
        if frame is None:  # D43: respuesta vacía = sin velas, con aviso; no es un error
            self.empty_notice = EmptyResponseNotice(
                instrument.provider_symbol, timeframe, eff_start, end
            )
            return []

        if timeframe is Timeframe.H4:
            hourly = self._intraday_candles(instrument, Timeframe.H1, frame)
            blocks = _resample_4h(drop_open_candle(hourly, Timeframe.H1, now))
            blocks = [(c, n) for c, n in blocks if eff_start <= c.ts < end]
            closed = drop_open_candle([c for c, _ in blocks], timeframe, now)
            closed_ts = {c.ts for c in closed}
            partial = sum(1 for c, n in blocks if c.ts in closed_ts and n < _H4_PARTS)
            if partial:
                self.partial_notice = PartialBlocksNotice(partial, len(closed))
            return closed

        if timeframe is Timeframe.D1:
            candles = self._daily_candles(instrument, frame)
        else:
            candles = self._intraday_candles(instrument, timeframe, frame)
        candles = [c for c in candles if eff_start <= c.ts < end]
        return drop_open_candle(candles, timeframe, now)

    def _clamp_start(self, timeframe: Timeframe, start: datetime, now: datetime) -> datetime:
        limit = _MAX_HISTORY.get(timeframe)
        if limit is None:
            return start
        earliest = now - limit
        if start >= earliest:
            return start
        if earliest - start > _NOTICE_TOLERANCE:
            self.history_notice = HistoryNotice(timeframe, start, earliest)
        return earliest

    async def _download(
        self, instrument: InstrumentSchema, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame | None:
        try:
            frame = await asyncio.to_thread(
                self._downloader, instrument.provider_symbol, _INTERVALS[timeframe], start, end
            )
        except Exception as exc:
            raise MarketDataError(f"Fallo al consultar Yahoo: {type(exc).__name__}") from exc
        if frame is None or len(frame) == 0:
            return None
        missing = [c for c in _COLUMNS if c not in frame.columns]
        if missing:
            raise MarketDataError(f"Respuesta de Yahoo sin las columnas: {', '.join(missing)}")
        return frame

    def _intraday_candles(
        self, instrument: InstrumentSchema, timeframe: Timeframe, frame: pd.DataFrame
    ) -> list[CandleSchema]:
        by_ts: dict[datetime, CandleSchema] = {}
        for stamp, row in frame.iterrows():
            ts = _to_datetime(stamp)
            if ts.tzinfo is None:
                raise MarketDataError("Yahoo devolvió marcas de tiempo sin zona horaria")
            candle = _build_candle(instrument, timeframe, ts.astimezone(UTC), row)
            if candle is not None:
                by_ts[candle.ts] = candle  # duplicados: gana el último
        return [by_ts[k] for k in sorted(by_ts)]

    def _daily_candles(
        self, instrument: InstrumentSchema, frame: pd.DataFrame
    ) -> list[CandleSchema]:
        """D32: Yahoo da la medianoche local del mercado; la vela es esa fecha a 00:00 UTC."""
        by_ts: dict[datetime, CandleSchema] = {}
        for stamp, row in frame.iterrows():
            local = _to_datetime(stamp)
            if local.time() != time(0, 0):
                raise MarketDataError(
                    f"No se puede alinear la vela diaria de Yahoo ({local.isoformat()}) "
                    "a 00:00 UTC sin ambigüedad"
                )
            day: date = local.date()
            ts = datetime(day.year, day.month, day.day, tzinfo=UTC)
            candle = _build_candle(instrument, Timeframe.D1, ts, row)
            if candle is None:
                continue
            previous = by_ts.get(ts)
            if previous is not None and previous != candle:
                raise MarketDataError(
                    f"Yahoo devolvió dos velas diarias distintas para {day.isoformat()}: "
                    "alineación diaria ambigua"
                )
            by_ts[ts] = candle
        return [by_ts[k] for k in sorted(by_ts)]


def _to_datetime(stamp: Any) -> datetime:
    try:
        value: datetime = pd.Timestamp(stamp).to_pydatetime()
    except (TypeError, ValueError) as exc:
        raise MarketDataError("Yahoo devolvió una marca de tiempo inválida") from exc
    return value


def _decimal(value: Any) -> Decimal:
    return Decimal(str(float(value)))  # D4: nunca Decimal(float)


def _build_candle(
    instrument: InstrumentSchema, timeframe: Timeframe, ts: datetime, row: Any
) -> CandleSchema | None:
    """Convierte una fila; `None` si algún precio es NaN. Volumen NaN o ausente = 0."""
    try:
        values = {name: float(row[name]) for name in _PRICES}
        if any(math.isnan(v) for v in values.values()):
            return None
        raw_volume = float(row["Volume"])
        volume = Decimal(0) if math.isnan(raw_volume) else _decimal(raw_volume)
        return CandleSchema(
            symbol=instrument.symbol,
            timeframe=timeframe,
            ts=ts,
            open=_decimal(values["Open"]),
            high=_decimal(values["High"]),
            low=_decimal(values["Low"]),
            close=_decimal(values["Close"]),
            volume=volume,
        )
    except (ValidationError, TypeError, ValueError, ArithmeticError) as exc:
        raise MarketDataError(f"Vela inválida de Yahoo: {exc}") from exc


def _resample_4h(hourly: list[CandleSchema]) -> list[tuple[CandleSchema, int]]:
    """D31: bloques de 4h alineados a 00/04/…/20 UTC con las velas de 1h presentes (>= 1).

    Devuelve cada bloque con el número de velas de 1h que lo componen (4 = completo).
    """
    blocks: dict[datetime, list[CandleSchema]] = {}
    for candle in hourly:
        blocks.setdefault(Timeframe.H4.floor(candle.ts), []).append(candle)
    out: list[tuple[CandleSchema, int]] = []
    for block_ts in sorted(blocks):
        parts = sorted(blocks[block_ts], key=lambda c: c.ts)
        merged = CandleSchema(
            symbol=parts[0].symbol,
            timeframe=Timeframe.H4,
            ts=block_ts,
            open=parts[0].open,
            high=max(c.high for c in parts),
            low=min(c.low for c in parts),
            close=parts[-1].close,
            volume=sum((c.volume for c in parts), Decimal(0)),
        )
        out.append((merged, len(parts)))
    return out
