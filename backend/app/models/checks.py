"""Utilidades para generar `CHECK` de enums (D7: TEXT + CHECK, sin ENUM nativo)."""

from enum import StrEnum


def enum_check(column: str, enum: type[StrEnum]) -> str:
    """Devuelve la expresión `column IN ('A', 'B', ...)` con los valores del enum."""
    values = ", ".join(f"'{member.value}'" for member in enum)
    return f"{column} IN ({values})"
