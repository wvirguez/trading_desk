# Validación — Proveedor provisional Yahoo Finance

## 1. Automatizado (CI y PR)

- Backend: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy app`, `uv run pytest` (incluidos los `@pytest.mark.db`, con la BD de test migrada a `head`).
- Frontend: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`. `npm run gen:api` no deja diff.
- Ningún test llama a Yahoo ni a la red.

Afirmaciones que deben existir en los tests:

| Afirmación | Dónde |
| :--- | :--- |
| Tras `upgrade head`, EUR/USD, XAU/USD y NAS100 son `YAHOO` con sus tickers; BTC/USDT sigue en `BINANCE`. | `tests/db` |
| `downgrade` y `upgrade` de `0005` funcionan. | `tests/db` |
| `YahooAdapter` devuelve velas alineadas, cerradas, en UTC y sin duplicados. | `tests/market_data` |
| Los precios son `Decimal` exactos (`Decimal(str(x))`). | `tests/market_data` |
| `Timeframe.M5` está alineado a 5 min, y `CandleSchema` rechaza un `ts` desalineado en `5m`. | `tests/schemas` |
| El remuestreo 4h agrupa las velas de 1h presentes (bloques parciales incluidos, avisados) y no emite bloques abiertos; `^NDX` 1h/4h lanza `UnsupportedTimeframeError` sin llamar al descargador, y la CLI `--all` lo omite (exit 0) mientras que la petición explícita da exit 1. | `tests/market_data` |
| Error de red o respuesta vacía → `MarketDataError` en español. | `tests/market_data` |
| La CLI avisa cuando Yahoo devuelve menos historia de la pedida. | `tests` |

## 2. Manual (smoke local, con red)

1. `uv run alembic upgrade head` y comprobar con `psql` que los 3 instrumentos son `YAHOO`.
2. `uv run python -m app.cli.ingest backfill --symbol EUR/USD --tf 1h`: debe terminar con exit code 0 y velas escritas.
3. Repetir con `--tf 5m`, `15m`, `4h` y `1d`, y con `XAU/USD` y `NAS100` (NAS100: solo `5m`, `15m` y `1d`; `1h` y `4h` deben dar el mensaje de no soportado y exit 1 si se piden explícitamente, y omitirse con `--all`). En `4h`, comprobar el aviso de bloques parciales. Si `XAUUSD=X` falla, anotarlo y pasar a `GC=F`.
4. `curl "http://localhost:8000/api/v1/market/ohlcv?symbol=EUR%2FUSD&tf=1h&limit=5"`: devuelve 5 velas ascendentes.
5. Confirmar que la salida avisa de la historia recortada en `5m` y `15m`.
6. Repetir el backfill: escribe 0 velas (idempotente).

Casos límite: fin de semana de FX (sin velas, sin error); `--since` anterior al límite de Yahoo (aviso, no fallo).

## 3. Tono

Mensajes en español, honestos y concretos. Nunca se presenta el dato de Yahoo como oficial.

## 4. Terminado cuando

Todo lo automatizado está en verde, el smoke manual pasa para los 3 instrumentos y sus timeframes soportados (NAS100 sin 1h/4h, D48) (o las limitaciones están documentadas), y `tech-stack.md` y el README reflejan que Yahoo es **provisional**. Se rechaza si hay una dependencia no aprobada o si `pandas` se usa fuera de `yahoo.py`.
