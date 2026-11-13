"""Enums de dominio compartidos por esquemas, modelos y adaptadores."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum


class AssetClass(StrEnum):
    CRYPTO = "CRYPTO"
    FX = "FX"
    METAL = "METAL"
    INDEX = "INDEX"


class Provider(StrEnum):
    BINANCE = "BINANCE"
    OANDA = "OANDA"
    YAHOO = "YAHOO"


class Timeframe(StrEnum):
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"

    @property
    def duration(self) -> timedelta:
        return _DURATIONS[self]

    def floor(self, dt: datetime) -> datetime:
        """Redondea `dt` hacia abajo al inicio de su vela, en UTC.

        Las velas se alinean con la época Unix (00:00 UTC), de modo que las diarias abren a
        00:00 UTC y las de 4h a 00, 04, 08, 12, 16 y 20 UTC.
        """
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("La fecha debe tener zona horaria")
        dt_utc = dt.astimezone(UTC)
        step = self.duration
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        return epoch + ((dt_utc - epoch) // step) * step


_DURATIONS: dict[Timeframe, timedelta] = {
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.H4: timedelta(hours=4),
    Timeframe.D1: timedelta(days=1),
}


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class SignalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


class SessionType(StrEnum):
    CRYPTO_24_7 = "CRYPTO_24_7"
    FX_24_5 = "FX_24_5"
    INDEX_CFD = "INDEX_CFD"
