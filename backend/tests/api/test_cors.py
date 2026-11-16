"""Tests de CORS."""

import pytest
from httpx import AsyncClient

URL = "/api/v1/market/instruments"


@pytest.mark.parametrize(
    "origin,expected_allowed",
    [
        ("http://localhost:3000", True),
        ("http://127.0.0.1:3000", False),
        ("http://example.com", False),
        ("null", False),
    ],
)
async def test_cors_origen_permitido(
    client: AsyncClient, origin: str, expected_allowed: bool
) -> None:
    response = await client.options(
        URL,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )

    if expected_allowed:
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == origin
    else:
        # Origen no permitido: no debe devolver access-control-allow-origin
        # o debe devolver un origen diferente / no coincidir
        allow_origin = response.headers.get("access-control-allow-origin")
        if allow_origin:
            assert allow_origin != origin
