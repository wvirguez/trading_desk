"""Acceso a `instruments` y conversión a `InstrumentSchema`."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instrument import Instrument
from app.schemas.enums import AssetClass, Provider, SessionType
from app.schemas.instrument import InstrumentSchema


def to_schema(row: Instrument) -> InstrumentSchema:
    return InstrumentSchema(
        symbol=row.symbol,
        asset_class=AssetClass(row.asset_class),
        provider=Provider(row.provider),
        provider_symbol=row.provider_symbol,
        base_currency=row.base_currency,
        quote_currency=row.quote_currency,
        tick_size=row.tick_size,
        lot_size=row.lot_size,
        session=SessionType(row.session),
    )


async def get_by_symbol(session: AsyncSession, symbol: str) -> Instrument | None:
    """Instrumento por símbolo canónico, o `None` si no existe."""
    stmt = select(Instrument).where(Instrument.symbol == symbol)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_all(session: AsyncSession) -> list[Instrument]:
    """Todos los instrumentos, ordenados por `id`."""
    return list((await session.execute(select(Instrument).order_by(Instrument.id))).scalars())
