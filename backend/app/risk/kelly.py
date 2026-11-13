"""Criterio de Kelly fraccional y riesgo de ruina (D61).

Unidades: ``p`` es la probabilidad de ganar en [0, 1]; ``b`` el ratio ganancia/pérdida (> 0);
``fraction``, ``cap`` y ``KellyResult.full_kelly/fraction`` son FRACCIONES del capital
(0.01 = 1 %), no porcentajes. ``risk_of_ruin`` recibe ``risk_pct`` también como fracción
0 < r <= 1 (0.01 = 1 % del capital por operación).
"""

import math

from app.schemas.risk import KellyResult


def _check_edge_inputs(p: float, b: float) -> None:
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"La probabilidad de acierto p debe estar en [0, 1] (recibido: {p})")
    if not b > 0.0 or math.isinf(b):
        raise ValueError(
            f"El ratio ganancia/pérdida b debe ser finito y mayor que 0 (recibido: {b})"
        )


def kelly_fraction(p: float, b: float, fraction: float, cap: float) -> KellyResult:
    """Kelly fraccional con tope.

    ``f* = p - (1 - p)/b``. Si ``f* <= 0`` no hay ventaja y la fracción aplicada es 0.
    ``aplicada = min(fraction * f*, cap)``; ``capped`` es True si el tope recortó.
    Supuestos: apuestas independientes e idénticas, resultado binario (gana ``b``, pierde 1)
    y estimaciones de ``p`` y ``b`` exactas (en la práctica son ruidosas: de ahí ``fraction``).
    """
    _check_edge_inputs(p, b)
    if not 0.0 < fraction <= 1.0:
        raise ValueError(f"La fracción de Kelly debe estar en (0, 1] (recibido: {fraction})")
    if not cap > 0.0:
        raise ValueError(f"El tope (cap) debe ser mayor que 0 (recibido: {cap})")
    full = max(p - (1.0 - p) / b, 0.0)
    wanted = fraction * full
    capped = wanted > cap
    return KellyResult(full_kelly=full, fraction=min(wanted, cap), capped=capped)


def risk_of_ruin(p: float, b: float, risk_pct: float) -> float:
    """Riesgo de ruina aproximado ``((1 - A)/(1 + A))^N``.

    ``A = p - (1 - p)/b`` es la ventaja y ``N = floor(1 / risk_pct)`` el número de unidades
    de riesgo que caben en el capital (``risk_pct`` es una fracción, 0.01 = 1 %).
    Devuelve 1.0 si ``A <= 0``; el resultado se acota a [0, 1]. Es una aproximación del
    paseo aleatorio con pasos simétricos de una unidad de riesgo: ignora el ratio ``b``
    salvo a través de ``A``, y el tamaño de posición constante sobre el capital inicial.
    """
    _check_edge_inputs(p, b)
    if not 0.0 < risk_pct <= 1.0:
        raise ValueError(
            f"El riesgo por operación debe ser una fracción en (0, 1] (recibido: {risk_pct})"
        )
    advantage = p - (1.0 - p) / b
    if advantage <= 0.0:
        return 1.0
    n = math.floor(1.0 / risk_pct)
    ratio = (1.0 - advantage) / (1.0 + advantage)
    return min(max(ratio**n, 0.0), 1.0)
