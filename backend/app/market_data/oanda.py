"""Adaptador de OANDA (REST v20, cuenta practice).

El `volume` de OANDA es **volumen de ticks** (número de actualizaciones de precio de la vela),
no volumen negociado: en FX OTC no existe volumen real (D13). Se guarda en la misma columna.
Las velas diarias se piden con `alignmentTimezone=UTC` y `dailyAlignment=0`, de modo que abren a
00:00 UTC como en el resto de proveedores (D6). El token nunca se registra ni aparece en errores.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.market_data.base import MarketDataError, drop_open_candle, utcnow
from app.schemas.candle import CandleSchema
from app.schemas.enums import Provider, Timeframe
from app.schemas.instrument import InstrumentSchema

log = structlog.get_logger(__name__)

PAGE_COUNT = 5000
_GRANULARITY: dict[Timeframe, str] = {
    Timeframe.M5: "M5",
    Timeframe.M15: "M15",
    Timeframe.H1: "H1",
    Timeframe.H4: "H4",
    Timeframe.D1: "D",
}
_FRACTION = re.compile(r"\.(\d+)Z$")


class _Mid(BaseModel):
    o: Decimal
    h: Decimal
    l: Decimal  # noqa: E741  (nombre del campo en la API v20)
    c: Decimal


class _RawCandle(BaseModel):
    complete: bool
    time: str
    volume: int
    mid: _Mid | None = None


class _RawResponse(BaseModel):
    candles: list[_RawCandle]


def _parse_time(value: str) -> datetime:
    """Interpreta `2024-01-05T20:00:00.000000000Z` (nanosegundos) como datetime UTC."""
    normalized = _FRACTION.sub(lambda m: f".{m.group(1)[:6]}+00:00", value)
    if normalized == value:
        normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(UTC)


def _format_time(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class OandaAdapter:
    """Velas OHLCV de OANDA. Con `owns_client=True` cierra el cliente al terminar."""

    provider = Provider.OANDA

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        now: Callable[[], datetime] = utcnow,
        owns_client: bool = False,
    ) -> None:
        self._client = client
        self._settings = settings
        self._now = now
        self._owns_client = owns_client

    async def fetch_ohlcv(
        self,
        instrument: InstrumentSchema,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[CandleSchema]:
        if instrument.provider is not Provider.OANDA:
            raise MarketDataError(
                f"El instrumento {instrument.symbol} es de {instrument.provider.value}, no de OANDA"
            )
        try:
            token = self._settings.oanda_api_token
            if token is None or not token.get_secret_value():
                raise MarketDataError("Falta OANDA_API_TOKEN")
            headers = {"Authorization": f"Bearer {token.get_secret_value()}"}
            candles = await self._paginate(instrument, timeframe, start, end, headers)
        finally:
            if self._owns_client:
                await self._client.aclose()
        return drop_open_candle(candles, timeframe, self._now())

    async def _paginate(
        self,
        instrument: InstrumentSchema,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        headers: dict[str, str],
    ) -> list[CandleSchema]:
        step = timeframe.duration
        cursor = timeframe.floor(start)
        by_ts: dict[datetime, CandleSchema] = {}
        while cursor < end:
            raw = await self._request(instrument, timeframe, cursor, headers)
            if not raw:
                break
            last_ts = cursor
            for item in raw:
                ts = _parse_time(item.time)
                last_ts = max(last_ts, ts)
                if not (item.complete and start <= ts < end):
                    continue
                if not isinstance(item.mid, _Mid):
                    log.warning(
                        "vela completa de OANDA sin precios mid; se descarta",
                        symbol=instrument.symbol,
                        timeframe=timeframe.value,
                        ts=ts.isoformat(),
                    )
                    continue
                by_ts[ts] = self._to_candle(instrument, timeframe, ts, item)
            cursor = last_ts + step
        return [by_ts[k] for k in sorted(by_ts)]

    async def _request(
        self,
        instrument: InstrumentSchema,
        timeframe: Timeframe,
        cursor: datetime,
        headers: dict[str, str],
    ) -> list[_RawCandle]:
        base = self._settings.oanda_base_url.rstrip("/")
        url = f"{base}/v3/instruments/{instrument.provider_symbol}/candles"
        params = {
            "price": "M",
            "granularity": _GRANULARITY[timeframe],
            "alignmentTimezone": "UTC",
            "dailyAlignment": "0",
            "from": _format_time(cursor),
            "count": str(PAGE_COUNT),
        }
        try:
            response = await self._client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise MarketDataError(
                f"Fallo de red al consultar OANDA ({type(exc).__name__})"
            ) from exc
        if response.status_code != httpx.codes.OK:
            raise MarketDataError(
                f"OANDA respondió {response.status_code}: {_error_message(response)}"
            )
        try:
            return _RawResponse.model_validate_json(response.content).candles
        except ValidationError as exc:
            raise MarketDataError(
                "Respuesta inesperada de OANDA: formato de velas inválido"
            ) from exc

    @staticmethod
    def _to_candle(
        instrument: InstrumentSchema, timeframe: Timeframe, ts: datetime, item: _RawCandle
    ) -> CandleSchema:
        mid = item.mid
        assert isinstance(mid, _Mid)  # noqa: S101  (filtrado por el llamador)
        try:
            return CandleSchema(
                symbol=instrument.symbol,
                timeframe=timeframe,
                ts=ts,
                open=mid.o,
                high=mid.h,
                low=mid.l,
                close=mid.c,
                volume=Decimal(item.volume),  # volumen de ticks (D13)
            )
        except ValidationError as exc:
            raise MarketDataError(f"Vela inválida de OANDA ({ts.isoformat()}): {exc}") from exc


def _error_message(response: httpx.Response) -> str:
    try:
        message = _ErrorBody.model_validate_json(response.content).errorMessage
    except ValidationError:
        message = None
    return message or response.reason_phrase or "sin detalle"


class _ErrorBody(BaseModel):
    errorMessage: str | None = None  # noqa: N815
