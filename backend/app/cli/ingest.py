"""CLI de ingesta OHLCV (D15): `python -m app.cli.ingest backfill|incremental ...`."""

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import get_sessionmaker
from app.core.logging import configure_logging
from app.market_data.base import MarketDataAdapter, UnsupportedTimeframeError, utcnow
from app.market_data.registry import adapter_for
from app.models.instrument import Instrument
from app.repositories import instruments as instruments_repo
from app.schemas.enums import Provider, Timeframe
from app.schemas.instrument import InstrumentSchema
from app.services import ingestion

AdapterFactory = Callable[[InstrumentSchema], MarketDataAdapter]
Clock = Callable[[], datetime]

_ALL_TFS = tuple(Timeframe)


def _parse_since(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Fecha inválida: {value!r} (use AAAA-MM-DD o ISO 8601)"
        ) from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _parse_tf(value: str) -> Timeframe:
    try:
        return Timeframe(value)
    except ValueError as exc:
        valid = ", ".join(t.value for t in Timeframe)
        raise argparse.ArgumentTypeError(
            f"Timeframe inválido: {value!r} (válidos: {valid})"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.ingest", description="Ingesta de velas OHLCV."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("backfill", "Descarga un rango histórico (por defecto, el horizonte configurado)."),
        ("incremental", "Descarga solo lo nuevo desde la última vela guardada."),
    ):
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.add_argument("--symbol", help="Símbolo canónico, p. ej. BTC/USDT.")
        p.add_argument("--tf", type=_parse_tf, help="Timeframe: 5m, 15m, 1h, 4h o 1d.")
        p.add_argument(
            "--all",
            action="store_true",
            help="Todos los instrumentos (y todos los timeframes si no se indica --tf).",
        )
        if name == "backfill":
            p.add_argument("--since", type=_parse_since, help="Inicio del rango (AAAA-MM-DD, UTC).")
    return parser


def _validate(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.all and args.symbol:
        parser.error("--all y --symbol son excluyentes")
    if not args.all and not args.symbol:
        parser.error("indique --symbol (con --tf) o --all")
    if not args.all and args.tf is None:
        parser.error("--symbol requiere --tf")


async def _process(
    sessionmaker: async_sessionmaker[AsyncSession],
    adapter_factory: AdapterFactory,
    command: str,
    instrument: Instrument,
    tf: Timeframe,
    since: datetime | None,
    now: datetime,
    settings: Settings,
) -> ingestion.IngestResult:
    adapter = adapter_factory(instruments_repo.to_schema(instrument))
    async with sessionmaker() as session:
        try:
            if command == "backfill":
                start = since or ingestion.default_since(
                    tf, now, settings, Provider(instrument.provider)
                )
                return await ingestion.backfill(session, adapter, instrument, tf, start, now=now)
            return await ingestion.incremental(
                session, adapter, instrument, tf, now=now, settings=settings
            )
        except BaseException:
            await session.rollback()
            raise


async def run(
    argv: Sequence[str],
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    adapter_factory: AdapterFactory | None = None,
    clock: Clock = utcnow,
    settings: Settings | None = None,
) -> int:
    """Ejecuta la CLI y devuelve el exit code (0 = todo bien, 1 = algún fallo)."""
    parser = build_parser()
    args = parser.parse_args(list(argv))
    _validate(parser, args)
    log = structlog.get_logger()
    cfg = settings or get_settings()
    maker = sessionmaker or get_sessionmaker()
    factory = adapter_factory or adapter_for
    since: datetime | None = getattr(args, "since", None)
    now = clock()

    async with maker() as session:
        rows = await instruments_repo.list_all(session)
    if args.all:
        selected = rows
    else:
        selected = [r for r in rows if r.symbol == args.symbol]
        if not selected:
            log.error("instrumento_desconocido", message=f"Instrumento desconocido: {args.symbol}")
            return 1
    timeframes = (args.tf,) if args.tf is not None else _ALL_TFS

    failures = 0
    skipped = 0
    written_total = 0
    for instrument in selected:
        for tf in timeframes:
            try:
                result = await _process(
                    maker, factory, args.command, instrument, tf, since, now, cfg
                )
            except UnsupportedTimeframeError as exc:
                if args.all:  # D48: con --all se omite; pedida explícitamente es un error
                    skipped += 1
                    log.warning(
                        "ingesta_omitida",
                        message=f"{instrument.symbol} {tf.value}: omitido: {exc}",
                        symbol=instrument.symbol,
                        timeframe=tf.value,
                    )
                    continue
                failures += 1
                log.error(
                    "ingesta_fallida",
                    message=f"Falló la ingesta de {instrument.symbol} {tf.value}: {exc}",
                    symbol=instrument.symbol,
                    timeframe=tf.value,
                    error=repr(exc),
                )
                continue
            except Exception as exc:
                failures += 1
                log.error(
                    "ingesta_fallida",
                    message=f"Falló la ingesta de {instrument.symbol} {tf.value}: {exc}",
                    symbol=instrument.symbol,
                    timeframe=tf.value,
                    error=repr(exc),
                )
                continue
            written_total += result.written
            event = "ingesta_ok" if result.fetched else "ingesta_sin_datos"
            message = (
                f"{instrument.symbol} {tf.value}: {result.fetched} velas recibidas, "
                f"{result.written} escritas"
                if result.fetched
                else f"{instrument.symbol} {tf.value}: no se descargó ninguna vela"
            )
            emit = log.info if result.fetched else log.warning
            emit(
                event,
                message=message,
                symbol=result.symbol,
                timeframe=tf.value,
                fetched=result.fetched,
                written=result.written,
                first_ts=result.first_ts.isoformat() if result.first_ts else None,
                last_ts=result.last_ts.isoformat() if result.last_ts else None,
            )
            for notice in result.notices:
                log.warning(
                    "aviso_ingesta",
                    message=f"{instrument.symbol} {tf.value}: {notice}",
                    symbol=instrument.symbol,
                    timeframe=tf.value,
                )

    total = len(selected) * len(timeframes) - skipped
    print(
        f"Resumen: {total - failures} de {total} ingestas correctas, {failures} con error, "
        f"{skipped} omitidas (no soportadas), {written_total} filas escritas."
    )
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    return asyncio.run(run(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    sys.exit(main())
