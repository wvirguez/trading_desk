# Validación — Fase 1: Datos y esquemas

La rama `phase-1-datos-y-esquemas` se integra en `main` **solo si se cumplen todos** los puntos siguientes. Cada punto indica cómo verificarlo.

## 1. Automatizado: CI en verde en la PR

- [ ] El job **backend** pasa:
  - `uv sync --frozen`.
  - `alembic upgrade head` (dev y test).
  - `ruff check` y `ruff format --check`.
  - `mypy app` (strict).
  - `pytest`, **incluidos** los tests `db`.
  - El `openapi.json` regenerado no tiene diff.
- [ ] El job **frontend** pasa:
  - `npm ci`.
  - `npm run lint`.
  - `npm run gen:api` sin diff en `types/api.ts`.
  - `npm run typecheck`.
  - `npm test`.
  - `npm run build`.
- [ ] La CI se ejecuta en la PR y **no hace ninguna llamada de red** a Binance ni a OANDA. Para comprobarlo, se busca en los tests cualquier construcción de `ccxt.binance` o de `httpx.AsyncClient` sin `MockTransport`.

### Afirmaciones que deben existir en los tests

| Área | Afirmación |
| :--- | :--- |
| `CandleSchema` | Rechaza un `ts` *naive*, un `ts` desalineado con el timeframe, `high < max(open, close)`, `low > min(open, close)`, precios ≤ 0 y volumen < 0. Normaliza `+02:00` a UTC. |
| Serialización | `model_dump(mode="json")` emite los precios como cadena: `Decimal("67000.12")` → `"67000.12"`. |
| Seed | Hay exactamente 4 instrumentos y sus `tick_size`/`lot_size` coinciden con `requirements.md` (o con los valores corregidos y registrados). |
| Hypertable | `ohlcv_bars` aparece en `timescaledb_information.hypertables`. |
| Upsert | La segunda ejecución con las mismas velas devuelve 0 escritas y el número de filas no cambia. Una vela con `close` distinto se actualiza. |
| `trade_signals` | Las señales nuevas nacen `PENDING` y un estado fuera de los 4 se rechaza en la base de datos. |
| Velas cerradas | ccxt descarta la última vela si `ts + duration > now`; OANDA descarta `complete: false`. |
| Decimal exacto | La conversión de ccxt produce `Decimal("0.1")`, no el valor binario de `float`. |
| OANDA | La petición lleva `price=M`, `alignmentTimezone=UTC`, `dailyAlignment=0` y la granularidad correcta. Las velas `D` empiezan a las 00:00 UTC. Un 401 → `MarketDataError`. Sin token → error que nombra `OANDA_API_TOKEN`. |
| Ingesta | El backfill es idempotente y el incremental re-pide solo desde la última vela. Un fallo en un instrumento no detiene a los demás y el *exit code* es 1. |
| Endpoint | 200 ascendente con exactamente `limit` velas; `[]` sin datos; 404 si el símbolo no existe; 422 si `tf` es inválido o `limit` vale 0 o 5001. |
| Contrato | `export_openapi` es determinista. `types/api.ts` tipa `open` como `string`. |

## 2. Manual: smoke test local

Se ejecuta en la máquina de desarrollo sobre `quant_terminal_db`.

| # | Paso | Resultado esperado |
| :--- | :--- | :--- |
| S1 | `cd backend && uv sync && uv run alembic upgrade head` | Se aplican `0002`–`0004` sin errores. |
| S2 | `psql … -c "select symbol, tick_size, lot_size from instruments"` | 4 filas con los valores del seed. |
| S3 | `uv run python -m app.cli.ingest backfill --symbol BTC/USDT --tf 1h --since <hace 3 días>` | Log JSON con `fetched ≈ 72` y `written` igual a `fetched`. *Exit code* 0. |
| S4 | Repetir S3 | `written: 0`. |
| S5 | `uv run python -m app.cli.ingest incremental --symbol BTC/USDT --tf 1h` | Escribe solo las velas nuevas (0 o 1 si no ha pasado una hora). |
| S6 | La última vela guardada | `ts + 1h ≤ now()`: no hay ninguna vela abierta en la tabla. |
| S7 | `uv run python -m app.cli.ingest incremental --symbol EUR/USD --tf 1h` **sin** `OANDA_API_TOKEN` | Mensaje claro en español que nombra `OANDA_API_TOKEN`. *Exit code* ≠ 0 y sin traza de excepción sin capturar. |
| S8 | `uv run uvicorn app.main:app --reload` y `curl 'localhost:8000/api/v1/market/ohlcv?symbol=BTC%2FUSDT&tf=1h&limit=5'` | 200 con 5 velas ascendentes, precios como cadena y `ts` en UTC (`Z` o `+00:00`). |
| S9 | Mismo `curl` con `symbol=XYZ`, `tf=2h` y `limit=0` | 404 con `detail` en español, 422 y 422. |
| S10 | `localhost:8000/docs` | Swagger muestra `/api/v1/market/ohlcv` con `CandleSchema`. |
| S11 | `cd frontend && npm run gen:api && git status` | Sin cambios. |

### Casos límite que hay que revisar a mano

- Un `--since` en el futuro: 0 velas, sin error.
- Un `--since` anterior al inicio del histórico de Binance: el backfill empieza en la primera vela disponible.
- Un backfill de `15m` que cruce un límite de chunk (más de 30 días): las filas quedan en varios chunks y el endpoint las devuelve ordenadas.

## 3. Tono de los textos visibles

Esta fase no tiene UI. Los textos visibles son los `detail` de la API y la salida de la CLI.

- [ ] Están en **español**, son técnicos y concretos, y nombran el dato problemático (símbolo, timeframe o variable de entorno).
- [ ] No esconden fallos: una ingesta con 0 velas lo dice y un instrumento que falla aparece en el log con su error.
- [ ] Ningún log ni mensaje de error contiene el valor de `OANDA_API_TOKEN`.

## 4. Documentación y specs

- [ ] El README documenta la CLI de ingesta y `npm run gen:api`, y su estructura de carpetas coincide con la real.
- [ ] El changelog de `tech-stack.md` recoge `ccxt`, `structlog`, `httpx` (runtime), `openapi-typescript`, `Decimal`/`NUMERIC` y `openapi.json` versionado.
- [ ] `requirements.md` recoge las decisiones de implementación (D21+) y el estado actualizado de la tabla de preguntas abiertas.

## 5. Cierre de 0.4

- [ ] Después del merge, el workflow `CI` en `main` está en verde (pestaña Actions de GitHub).
- [ ] `roadmap.md` marca **0.4** y **1.1–1.9** como `[x]`.

## Definición de terminado

La fase está terminada cuando:

1. Las secciones 1–5 están marcadas.
2. La base de datos local contiene velas reales y cerradas de BTC/USDT, servidas por `GET /api/v1/market/ohlcv`.
3. Los tipos TS se generan desde el contrato y la CI impide que se desincronicen.
4. Lo único pendiente es la validación real contra OANDA, y está registrado en la sección 6 de `requirements.md`.

## Criterio de rechazo

Si cualquier punto falla, la PR no se integra. Si un punto resulta inviable, la decisión se registra en `requirements.md` antes de integrar. **No se hace merge sin dejar constancia.**
