"""Estructura de mercado: swings, BOS/CHoCH y fair value gaps (D68, sin look-ahead D55).

Funciones puras sobre un `polars.DataFrame` con columnas `ts`, `high`, `low` y `close`
(float64, ver `app.quant.data`). Los precios se convierten a `Decimal(str(x))` solo en la
frontera hacia los esquemas.

Ambigüedades resueltas (definiciones operativas):

- Empates: un swing exige máximo/mínimo *estricto* en `[i-n, i+n]`; si otra vela de la ventana
  iguala el extremo, no hay swing. Romper un nivel exige cierre *estrictamente* mayor/menor;
  un cierre igual al nivel no rompe.
- Una misma vela puede ser a la vez swing alto y swing bajo (vela envolvente); se emiten los
  dos, el alto primero.
- Un swing solo es utilizable en velas posteriores a su `confirmed_at` (no en la propia vela
  de confirmación).
- "Último swing" = el confirmado más recientemente de cada tipo. Si ya fue roto, no hay nivel
  que romper en ese lado hasta que se confirme otro swing de ese tipo (aunque sea menos
  extremo). Cada swing se rompe a lo sumo una vez.
- La primera ruptura (tendencia indefinida) se clasifica como BOS y fija la tendencia.
- Como mucho un evento por vela: si el cierre rompe a la vez el último swing alto y el bajo
  (solo posible si el alto está por debajo del bajo), se emite el del swing más reciente y
  el otro queda sin romper.
- FVG: la mitigación usa el rango inclusivo de la vela (`low <= zona.high` y
  `high >= zona.low`): tocar el borde cuenta. La vela `i+1` que forma el gap no mitiga.
"""

from datetime import datetime
from decimal import Decimal

import polars as pl

from app.schemas.enums import Direction, StructureEventType, SwingKind
from app.schemas.quant import FairValueGap, MarketStructureResult, StructureEvent, SwingPoint


def _dec(x: float) -> Decimal:
    return Decimal(str(x))


def find_swings(df: pl.DataFrame, n: int = 3) -> list[SwingPoint]:
    """Swings de ventana `n`: alto si `high[i]` es el máximo estricto de `[i-n, i+n]`.

    El bajo es análogo con `low` y el mínimo estricto. `confirmed_at` es el `ts` de la vela
    `i+n` (D55). Con menos de `2n+1` velas no hay swings. Orden: por `ts`, alto antes que bajo.
    """
    if n < 1:
        raise ValueError("n debe ser al menos 1")
    size = df.height
    ts: list[datetime] = df["ts"].to_list()
    highs: list[float] = df["high"].to_list()
    lows: list[float] = df["low"].to_list()
    swings: list[SwingPoint] = []
    for i in range(n, size - n):
        others = [j for j in range(i - n, i + n + 1) if j != i]
        if all(highs[i] > highs[j] for j in others):
            swings.append(
                SwingPoint(
                    ts=ts[i], kind=SwingKind.HIGH, price=_dec(highs[i]), confirmed_at=ts[i + n]
                )
            )
        if all(lows[i] < lows[j] for j in others):
            swings.append(
                SwingPoint(
                    ts=ts[i], kind=SwingKind.LOW, price=_dec(lows[i]), confirmed_at=ts[i + n]
                )
            )
    return swings


def find_structure_events(df: pl.DataFrame, swings: list[SwingPoint]) -> list[StructureEvent]:
    """BOS y CHoCH por cierre que rompe el último swing confirmado (D68).

    - BOS: ruptura en el sentido de la tendencia vigente (continuación). La primera ruptura,
      con tendencia indefinida, es BOS y fija la tendencia.
    - CHoCH: ruptura en sentido contrario a la tendencia vigente; invierte la tendencia.
    - Ruptura alcista = cierre > último swing alto (dirección LONG); bajista = cierre <
      último swing bajo (SHORT).
    Un swing solo es utilizable desde la vela siguiente a su `confirmed_at` y se rompe una
    sola vez. Resultado ordenado por `ts`.
    """
    ts: list[datetime] = df["ts"].to_list()
    closes: list[float] = df["close"].to_list()
    pending = sorted(swings, key=lambda s: (s.confirmed_at, s.ts))
    nxt = 0
    last_high: SwingPoint | None = None
    last_low: SwingPoint | None = None
    trend: Direction | None = None
    events: list[StructureEvent] = []
    for t, close in enumerate(closes):
        while nxt < len(pending) and pending[nxt].confirmed_at < ts[t]:
            sw = pending[nxt]
            if sw.kind is SwingKind.HIGH:
                last_high = sw
            else:
                last_low = sw
            nxt += 1
        broken: SwingPoint | None = None
        direction = Direction.LONG
        up = last_high is not None and close > float(last_high.price)
        down = last_low is not None and close < float(last_low.price)
        if last_high is not None and last_low is not None and up and down:
            # Ambos rotos a la vez: solo el swing más reciente genera evento.
            up = last_high.ts >= last_low.ts
            down = not up
        if up:
            broken = last_high
            last_high = None
        elif down:
            broken = last_low
            last_low = None
            direction = Direction.SHORT
        if broken is None:
            continue
        kind = (
            StructureEventType.BOS
            if trend is None or trend is direction
            else StructureEventType.CHOCH
        )
        trend = direction
        events.append(
            StructureEvent(
                ts=ts[t],
                type=kind,
                direction=direction,
                broken_swing_ts=broken.ts,
                level=broken.price,
            )
        )
    return events


def find_fvgs(df: pl.DataFrame) -> list[FairValueGap]:
    """Fair value gaps de tres velas centradas en `i` (`ts` = vela central).

    Alcista: `low[i+1] > high[i-1]`, zona `[high[i-1], low[i+1]]`. Bajista:
    `high[i+1] < low[i-1]`, zona `[high[i+1], low[i-1]]`. `mitigated_at` es el `ts` de la
    primera vela `j > i+1` cuyo rango toca o entra en la zona; `None` si no hay. Ordenado por `ts`.
    """
    ts: list[datetime] = df["ts"].to_list()
    highs: list[float] = df["high"].to_list()
    lows: list[float] = df["low"].to_list()
    size = df.height
    fvgs: list[FairValueGap] = []
    for i in range(1, size - 1):
        if lows[i + 1] > highs[i - 1]:
            direction, zlow, zhigh = Direction.LONG, highs[i - 1], lows[i + 1]
        elif highs[i + 1] < lows[i - 1]:
            direction, zlow, zhigh = Direction.SHORT, highs[i + 1], lows[i - 1]
        else:
            continue
        mitigated_at = next(
            (ts[j] for j in range(i + 2, size) if lows[j] <= zhigh and highs[j] >= zlow),
            None,
        )
        fvgs.append(
            FairValueGap(
                ts=ts[i],
                direction=direction,
                low=_dec(zlow),
                high=_dec(zhigh),
                mitigated_at=mitigated_at,
            )
        )
    return fvgs


def analyze_structure(df: pl.DataFrame, n: int = 3) -> MarketStructureResult:
    """Swings, eventos de estructura y FVG de `df` (D68), todo ordenado por `ts`."""
    swings = find_swings(df, n)
    return MarketStructureResult(
        swings=swings, events=find_structure_events(df, swings), fvgs=find_fvgs(df)
    )
