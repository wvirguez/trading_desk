import json
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest

from app.core.config import Settings
from app.market_data.base import MarketDataError
from app.market_data.oanda import OandaAdapter
from app.schemas.enums import Provider, Timeframe
from app.schemas.instrument import InstrumentSchema
from tests.market_data.conftest import load_fixture, utc

TOKEN = "token-secreto-de-prueba"  # noqa: S105


def _settings(token: str | None = TOKEN) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        oanda_api_token=token,  # type: ignore[arg-type]
        oanda_base_url="https://api-fxpractice.oanda.com",
    )


def _adapter(
    handler: httpx.MockTransport, token: str | None = TOKEN, now_hour: int = 0
) -> OandaAdapter:
    client = httpx.AsyncClient(transport=handler)
    return OandaAdapter(client, _settings(token), now=lambda: utc(2024, 1, 10, now_hour))


async def test_construye_url_y_parametros(eurusd: InstrumentSchema) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=load_fixture("oanda_eurusd_h1.json"))

    adapter = _adapter(httpx.MockTransport(handler))
    candles = await adapter.fetch_ohlcv(
        eurusd, Timeframe.H1, utc(2024, 1, 5, 20), utc(2024, 1, 8, 1)
    )

    assert adapter.provider is Provider.OANDA
    assert len(seen) == 1
    req = seen[0]
    assert req.method == "GET"
    assert req.url.scheme == "https" and req.url.host == "api-fxpractice.oanda.com"
    assert req.url.path == "/v3/instruments/EUR_USD/candles"
    params = dict(req.url.params)
    assert params == {
        "price": "M",
        "granularity": "H1",
        "alignmentTimezone": "UTC",
        "dailyAlignment": "0",
        "from": "2024-01-05T20:00:00Z",
        "count": "5000",
    }
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"
    # 4 completas; la vela del 08/01 00:00 es incompleta y se descarta.
    assert [c.ts for c in candles] == [
        utc(2024, 1, 5, 20),
        utc(2024, 1, 5, 21),
        utc(2024, 1, 7, 22),
        utc(2024, 1, 7, 23),
    ]
    assert candles[0].open == Decimal("1.09450")
    assert str(candles[0].close) == "1.09500"
    assert candles[0].volume == Decimal(1520)


@pytest.mark.parametrize(
    ("granularity", "tf"),
    [
        ("M5", Timeframe.M5),
        ("M15", Timeframe.M15),
        ("H1", Timeframe.H1),
        ("H4", Timeframe.H4),
        ("D", Timeframe.D1),
    ],
)
async def test_mapea_granularidad(
    granularity: str, tf: Timeframe, eurusd: InstrumentSchema
) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["granularity"])
        return httpx.Response(
            200, json={"instrument": "EUR_USD", "granularity": "x", "candles": []}
        )

    await _adapter(httpx.MockTransport(handler)).fetch_ohlcv(
        eurusd, tf, utc(2024, 1, 1), utc(2024, 1, 2)
    )
    assert seen == [granularity]


async def test_pagina_hasta_end(eurusd: InstrumentSchema) -> None:
    rows = load_fixture("oanda_eurusd_h1.json")
    froms: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        froms.append(request.url.params["from"])
        part = rows["candles"][:2] if len(froms) == 1 else rows["candles"][2:]
        return httpx.Response(200, json={**rows, "candles": part})

    candles = await _adapter(httpx.MockTransport(handler)).fetch_ohlcv(
        eurusd, Timeframe.H1, utc(2024, 1, 5, 20), utc(2024, 1, 8, 1)
    )
    assert froms == ["2024-01-05T20:00:00Z", "2024-01-05T22:00:00Z"]
    assert len(candles) == 4


async def test_velas_diarias_alineadas_a_00_utc(xauusd: InstrumentSchema) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["granularity"] == "D"
        assert request.url.params["dailyAlignment"] == "0"
        assert request.url.params["alignmentTimezone"] == "UTC"
        return httpx.Response(200, json=load_fixture("oanda_xauusd_d.json"))

    candles = await _adapter(httpx.MockTransport(handler)).fetch_ohlcv(
        xauusd, Timeframe.D1, utc(2024, 1, 3), utc(2024, 1, 10)
    )
    assert [c.ts.day for c in candles] == [3, 4, 5, 8]  # hueco de fin de semana, 09 incompleta
    assert all(c.ts.hour == 0 and c.ts.minute == 0 for c in candles)
    assert candles[0].high == Decimal("2050.100")


async def test_nas100_m15_descarta_incompletas_aunque_el_reloj_las_de_por_cerradas(
    nas100: InstrumentSchema,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/instruments/NAS100_USD/candles"
        return httpx.Response(200, json=load_fixture("oanda_nas100_m15.json"))

    candles = await _adapter(httpx.MockTransport(handler)).fetch_ohlcv(
        nas100, Timeframe.M15, utc(2024, 1, 5, 21, 30), utc(2024, 1, 8)
    )
    assert [(c.ts.day, c.ts.hour, c.ts.minute) for c in candles] == [
        (5, 21, 30),
        (5, 21, 45),
        (7, 23, 0),
        (7, 23, 15),
    ]
    assert candles[-1].ts + timedelta(minutes=15) <= utc(2024, 1, 10)


async def test_descarta_velas_abiertas_por_reloj(eurusd: InstrumentSchema) -> None:
    rows = load_fixture("oanda_eurusd_h1.json")
    rows["candles"][-1]["complete"] = True  # el proveedor dice completa pero el reloj no

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OandaAdapter(client, _settings(), now=lambda: utc(2024, 1, 8, 0, 30))
    candles = await adapter.fetch_ohlcv(
        eurusd, Timeframe.H1, utc(2024, 1, 5, 20), utc(2024, 1, 8, 1)
    )
    assert candles[-1].ts == utc(2024, 1, 7, 23)


async def test_401_se_convierte_en_market_data_error(eurusd: InstrumentSchema) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errorMessage": "Insufficient authorization"})

    with pytest.raises(MarketDataError) as exc:
        await _adapter(httpx.MockTransport(handler)).fetch_ohlcv(
            eurusd, Timeframe.H1, utc(2024, 1, 1), utc(2024, 1, 2)
        )
    assert "401" in str(exc.value)
    assert "Insufficient authorization" in str(exc.value)
    assert TOKEN not in str(exc.value)


async def test_error_de_red_no_filtra_el_token(eurusd: InstrumentSchema) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexión", request=request)

    with pytest.raises(MarketDataError) as exc:
        await _adapter(httpx.MockTransport(handler)).fetch_ohlcv(
            eurusd, Timeframe.H1, utc(2024, 1, 1), utc(2024, 1, 2)
        )
    assert TOKEN not in str(exc.value)


async def test_sin_token_error_claro_y_sin_peticion(eurusd: InstrumentSchema) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"candles": []})

    with pytest.raises(MarketDataError, match="Falta OANDA_API_TOKEN"):
        await _adapter(httpx.MockTransport(handler), token=None).fetch_ohlcv(
            eurusd, Timeframe.H1, utc(2024, 1, 1), utc(2024, 1, 2)
        )
    assert calls == []


async def test_respuesta_malformada(eurusd: InstrumentSchema) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"candles": [{"time": "x"}]}).encode())

    with pytest.raises(MarketDataError, match="inesperada"):
        await _adapter(httpx.MockTransport(handler)).fetch_ohlcv(
            eurusd, Timeframe.H1, utc(2024, 1, 1), utc(2024, 1, 2)
        )


async def test_rechaza_instrumento_de_otro_proveedor(btc: InstrumentSchema) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candles": []})

    with pytest.raises(MarketDataError, match="OANDA"):
        await _adapter(httpx.MockTransport(handler)).fetch_ohlcv(
            btc, Timeframe.H1, utc(2024, 1, 1), utc(2024, 1, 2)
        )


async def test_sin_token_cierra_el_cliente_propio(eurusd: InstrumentSchema) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    adapter = OandaAdapter(client, _settings(None), now=lambda: utc(2024, 1, 10), owns_client=True)
    with pytest.raises(MarketDataError, match="Falta OANDA_API_TOKEN"):
        await adapter.fetch_ohlcv(eurusd, Timeframe.H1, utc(2024, 1, 1), utc(2024, 1, 2))
    assert client.is_closed


async def test_vela_completa_sin_mid_se_descarta(eurusd: InstrumentSchema) -> None:
    body = {
        "candles": [
            {"time": "2024-01-01T00:00:00.000000000Z", "complete": True, "volume": 3},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    candles = await _adapter(httpx.MockTransport(handler)).fetch_ohlcv(
        eurusd, Timeframe.H1, utc(2024, 1, 1), utc(2024, 1, 2)
    )
    assert candles == []
