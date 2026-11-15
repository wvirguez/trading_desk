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


class RegimeLabel(StrEnum):
    MEAN_REVERTING = "MEAN_REVERTING"
    TRENDING = "TRENDING"
    HIGH_VOLATILITY_NOISE = "HIGH_VOLATILITY_NOISE"


class StructureEventType(StrEnum):
    BOS = "BOS"
    CHOCH = "CHOCH"


class SwingKind(StrEnum):
    HIGH = "HIGH"
    LOW = "LOW"


class VetoReason(StrEnum):
    RR_BELOW_MIN = "RR_BELOW_MIN"
    RISK_PER_TRADE_EXCEEDED = "RISK_PER_TRADE_EXCEEDED"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    OPEN_RISK_LIMIT = "OPEN_RISK_LIMIT"
    CORRELATED_RISK_LIMIT = "CORRELATED_RISK_LIMIT"
    SIZE_BELOW_LOT = "SIZE_BELOW_LOT"
    INVALID_LEVELS = "INVALID_LEVELS"


class Bias(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Playbook(StrEnum):
    MEAN_REVERSION = "MEAN_REVERSION"
    TREND_FOLLOWING = "TREND_FOLLOWING"
    NO_TRADE = "NO_TRADE"


class AuditDecision(StrEnum):
    APPROVE = "APPROVE"
    VETO = "VETO"


class AnalysisStep(StrEnum):
    STRUCTURE = "STRUCTURE"
    QUANT = "QUANT"
    PROPOSAL = "PROPOSAL"
    GUARDS = "GUARDS"
    RISK_AUDIT = "RISK_AUDIT"


class AnalysisOutcome(StrEnum):
    SIGNAL_APPROVED = "SIGNAL_APPROVED"
    SIGNAL_REJECTED = "SIGNAL_REJECTED"
    NO_TRADE = "NO_TRADE"
