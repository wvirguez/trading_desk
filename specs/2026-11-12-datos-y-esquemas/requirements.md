# Requisitos — Fase 1: Datos y esquemas

- **Rama:** `phase-1-datos-y-esquemas`
- **Roadmap:** pasos 1.1 – 1.9 de [`specs/roadmap.md`](../roadmap.md), más el cierre del paso pendiente **0.4** (CI en verde en `main`)
- **Referencias:** [`mission.md`](../mission.md), [`tech-stack.md`](../tech-stack.md), spec anterior [`2026-11-12-cimientos-repositorio`](../2026-11-12-cimientos-repositorio/requirements.md)

## 1. Contexto

El Bloque 0 dejó un backend FastAPI con `/health`, Alembic con `0001_baseline`, una CI con un *service* de Timescale y un frontend Next.js sin llamadas al backend. Ninguna fase posterior puede avanzar sin datos: el motor cuantitativo (Fase 2) y los agentes (Fase 3) consumen velas OHLCV normalizadas, y la UI (Fase 4) consume tipos TypeScript generados.

Esta fase da a la aplicación los **contratos de dominio**, las **tablas** y la **ingesta de velas** de los 4 instrumentos del MVP, y expone el primer endpoint de datos con su tipo TS generado. Cumple el criterio de éxito de la misión *"Ingesta de OHLCV histórica e incremental para los 4 instrumentos y los 4 marcos temporales"* y el principio 1 (esquemas primero, tipos generados).

El paso **0.4** tiene el workflow implementado (`e0bf49a`), pero nunca se comprobó en verde en GitHub. Se cierra dentro de esta fase.

## 2. Alcance

### Dentro del alcance

1. **1.1 Esquemas de dominio:** los enums `AssetClass`, `Timeframe`, `Direction`, `SignalStatus` y `Provider`, más `InstrumentSchema` y `CandleSchema`.
2. **1.2 `instruments`:** modelo, migración y seed de los 4 instrumentos.
3. **1.3 `ohlcv_bars`:** hypertable con clave `(instrument_id, timeframe, ts)` y upsert idempotente.
4. **1.4 `trade_signals`:** tabla y migración con los 4 estados.
5. **1.5 `MarketDataAdapter`:** protocolo común, normalización a `CandleSchema` en UTC y adaptador *fake*.
6. **1.6 Adaptador ccxt:** OHLCV paginado de BTC/USDT (Binance, datos públicos).
7. **1.7 Adaptador OANDA:** EUR/USD, XAU/USD y NAS100_USD (REST v20, cuenta practice), **probado solo con fixtures** (véase D12).
8. **1.8 Servicio de ingesta:** backfill e ingesta incremental por instrumento y timeframe, con un comando CLI.
9. **1.9 `GET /api/v1/market/ohlcv`:** devuelve `list[CandleSchema]`, genera `openapi-typescript` y la CI comprueba que los tipos están al día.
10. **0.4:** la CI pasa en verde en la PR y en `main`; el roadmap marca 0.4 como hecho.

### Fuera del alcance

- Programar la ingesta (APScheduler o tareas periódicas): en esta fase la ingesta se lanza a mano por CLI.
- Ticks y WebSocket: paso 4.4.
- `TradeSignalSchema` canónico y lógica de señales: paso 3.1. Aquí solo se crea la **tabla**.
- Agregados continuos y compresión de Timescale: post-MVP.
- Detección y relleno de huecos (*gaps*) más allá de lo que da la ingesta incremental.
- Cualquier consumo del endpoint desde la UI: Fase 4. Solo se generan los tipos.
- Llamadas reales a OANDA en CI o en los tests (véase D12).

### Instrumentos (seed)

Los valores de tick y lote son **provisionales**. Se contrastan durante la implementación con `exchangeInfo` de Binance (público) y, cuando exista cuenta, con `GET /v3/accounts/{id}/instruments` de OANDA (véase la sección 6).

| `symbol` | `asset_class` | `provider` | `provider_symbol` | `tick_size` | `lot_size` | `session` |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `BTC/USDT` | `CRYPTO` | `BINANCE` | `BTC/USDT` | `0.01` | `0.00001` | `CRYPTO_24_7` |
| `EUR/USD` | `FX` | `OANDA` | `EUR_USD` | `0.00001` | `1` | `FX_24_5` |
| `XAU/USD` | `METAL` | `OANDA` | `XAU_USD` | `0.001` | `1` | `FX_24_5` |
| `NAS100` | `INDEX` | `OANDA` | `NAS100_USD` | `0.1` | `0.1` | `INDEX_CFD` |

### Esquemas

**Enums** (`app/schemas/enums.py`; todos `StrEnum`):

| Enum | Valores |
| :--- | :--- |
| `AssetClass` | `CRYPTO`, `FX`, `METAL`, `INDEX` |
| `Provider` | `BINANCE`, `OANDA` |
| `Timeframe` | `M15 = "15m"`, `H1 = "1h"`, `H4 = "4h"`, `D1 = "1d"` (con la propiedad `duration: timedelta`) |
| `Direction` | `LONG`, `SHORT` |
| `SignalStatus` | `PENDING`, `APPROVED`, `REJECTED`, `EXECUTED` |
| `SessionType` | `CRYPTO_24_7`, `FX_24_5`, `INDEX_CFD` |

**`InstrumentSchema`** (inmutable, `frozen=True`): `symbol`, `asset_class`, `provider`, `provider_symbol`, `base_currency`, `quote_currency`, `tick_size: Decimal > 0`, `lot_size: Decimal > 0`, `session: SessionType`.

**`CandleSchema`** (inmutable):

| Campo | Tipo | Regla |
| :--- | :--- | :--- |
| `symbol` | `str` | Símbolo canónico (`BTC/USDT`, …). |
| `timeframe` | `Timeframe` | — |
| `ts` | `datetime` | **Apertura** de la vela. Debe tener zona horaria y se normaliza a UTC; si es *naive*, se rechaza. Debe estar alineada con el timeframe (p. ej. `:00/:15/:30/:45` en `15m` y `00:00 UTC` en `1d`). |
| `open`, `high`, `low`, `close` | `Decimal` | `> 0`; `high ≥ max(open, close, low)` y `low ≤ min(open, close)`. |
| `volume` | `Decimal` | `≥ 0`. En OANDA es volumen de ticks (véase D13). |

### Tablas

| Tabla | Columnas clave | Notas |
| :--- | :--- | :--- |
| `instruments` | `id SMALLINT` PK, `symbol` único, los campos de `InstrumentSchema`, `created_at` | `tick_size` y `lot_size` en `NUMERIC(20,10)`. |
| `ohlcv_bars` | PK `(instrument_id, timeframe, ts)`, `open/high/low/close NUMERIC(24,10)`, `volume NUMERIC(30,10)`, `ingested_at` | Hypertable sobre `ts`, chunks de 30 días. FK a `instruments`. `CHECK` de coherencia OHLC. |
| `trade_signals` | `id UUID` (`uuid_generate_v4()`), `instrument_id`, `timeframe`, `direction`, `entry`, `stop_loss`, `take_profit` (`NUMERIC(24,10)`), `status` (por defecto `PENDING`), `created_at`, `updated_at` | Mínima. Las columnas de razonamiento, tamaño y R:R se añaden en la Fase 3 con migraciones propias. |

### Endpoint

`GET /api/v1/market/ohlcv?symbol=BTC/USDT&tf=1h&limit=500`

- `symbol`: símbolo canónico (en la URL va codificado, `BTC%2FUSDT`). Si no existe → **404**.
- `tf`: valor de `Timeframe`. Si no es válido → **422**.
- `limit`: entero entre 1 y 5000, por defecto 500. Fuera de rango → **422**.
- Respuesta **200**: `list[CandleSchema]` con las **últimas** `limit` velas, en orden **ascendente** de `ts`. Si no hay datos, lista vacía.

### Comando CLI

```bash
uv run python -m app.cli.ingest backfill    --symbol BTC/USDT --tf 1h [--since 2024-01-01]
uv run python -m app.cli.ingest incremental --symbol BTC/USDT --tf 1h
uv run python -m app.cli.ingest incremental --all
```

## 3. Decisiones

| # | Decisión | Motivo |
| :--- | :--- | :--- |
| D1 | **Una sola spec para la Fase 1 completa** (1.1–1.9). El plan se divide en grupos con un commit verde cada uno. | Elegido por el usuario; mantiene la granularidad de la spec del Bloque 0. |
| D2 | **Precios y tamaños en `Decimal`** en Pydantic y `NUMERIC` en Postgres. Nunca `float` en esquemas ni en tablas. | Elegido por el usuario. Reproducibilidad (principio 6) y aritmética exacta de ticks y lotes para el *sizing* de la Fase 2. |
| D3 | En JSON, los `Decimal` se serializan como **cadena** (comportamiento por defecto de Pydantic v2), y así aparecen en OpenAPI y en los tipos TS. | No se pierde precisión en el transporte. El frontend convertirá a número solo para dibujar. |
| D4 | Las conversiones `float → Decimal` (ccxt devuelve `float`) se hacen con `Decimal(str(x))`, nunca con `Decimal(x)`. | `str` da la representación decimal más corta; `Decimal(0.1)` arrastraría el error binario. |
| D5 | **Solo se persisten velas cerradas.** Una vela es cerrada si `ts + timeframe.duration ≤ now`. OANDA aporta además el campo `complete`, que debe ser `true`. El reloj (`now`) se inyecta para poder testearlo. | Elegido por el usuario. Una vela en curso cambiaría después de guardarse y rompería la reproducibilidad. |
| D6 | `ts` es la **hora de apertura** en UTC. Las velas diarias empiezan a las **00:00 UTC** en todos los proveedores: a OANDA se le piden con `alignmentTimezone=UTC` y `dailyAlignment=0`. | Por defecto OANDA alinea las diarias a las 17:00 de Nueva York, lo que haría incomparables cripto y FX. |
| D7 | Los enums se guardan en Postgres como `TEXT` con `CHECK (… IN (…))`, no como tipos `ENUM` nativos. | Añadir un valor es una migración trivial; con `ENUM` nativo, `ALTER TYPE` tiene restricciones dentro de transacciones. |
| D8 | El **seed** de `instruments` es una **migración de datos** de Alembic (`INSERT … ON CONFLICT (symbol) DO NOTHING`). | Queda versionado y se aplica igual en desarrollo, en test y en CI sin pasos extra. |
| D9 | Upsert de velas: `INSERT … ON CONFLICT (instrument_id, timeframe, ts) DO UPDATE` **solo si algún valor cambia** (`WHERE` con `IS DISTINCT FROM`). Por lotes de hasta 1000 filas. | Idempotente (ejecutar dos veces deja la misma tabla) y admite correcciones del proveedor sin reescribir filas iguales. |
| D10 | **Dependencias aprobadas:** `ccxt` (runtime), `httpx` (pasa de dev a runtime) y `structlog` (runtime). En el frontend, `openapi-typescript` (dev). | Elegido por el usuario. No se añade ninguna otra sin preguntar (ni `respx`, ni `typer`, ni `vcrpy`). |
| D11 | **Tests con respuestas grabadas a mano**, como fixtures JSON versionados en `tests/fixtures/`. ccxt se prueba inyectando un exchange falso que devuelve el fixture; OANDA con `httpx.MockTransport` (incluido en httpx). **La CI nunca llama a la red.** | Elegido por el usuario. `MockTransport` evita añadir `respx`. |
| D12 | **Sin cuenta OANDA todavía.** El adaptador se implementa contra la documentación de la REST v20 y fixtures construidos a mano con su formato. `OANDA_API_TOKEN` y `OANDA_ACCOUNT_ID` son opcionales: si faltan, el adaptador falla con un error claro al usarse, no al arrancar la app. La validación real queda **pendiente** y registrada (sección 6). | Elegido por el usuario. No bloquea la fase. |
| D13 | El volumen de OANDA es **volumen de ticks**; se guarda en la misma columna `volume` y se documenta en el docstring del adaptador. | No existe volumen real en FX OTC. Separarlo en otra columna no aporta nada a las fases siguientes. |
| D14 | `MarketDataAdapter` es un `typing.Protocol` con `provider` y `async fetch_ohlcv(instrument, timeframe, start, end) -> list[CandleSchema]`. La paginación es interna al adaptador. Velas en orden ascendente y sin duplicados. | El servicio de ingesta no sabe nada de los proveedores; el adaptador *fake* sirve para testear la ingesta y el endpoint. |
| D15 | La CLI usa `argparse` (biblioteca estándar). | Sin dependencias nuevas. |
| D16 | Ingesta incremental: parte del `max(ts)` guardado para ese instrumento y timeframe y **re-pide la última vela** guardada (el upsert la deja igual o la corrige). Si no hay datos, cae al backfill con el horizonte por defecto. | Simple y robusta ante cortes. |
| D17 | Horizontes de backfill por defecto, configurables en `Settings`: `15m` → 365 días; `1h`, `4h` y `1d` → 5 años. | Suficiente para backtests de la Fase 2 sin descargas enormes. |
| D18 | Contrato OpenAPI: `backend/scripts/export_openapi.py` escribe `backend/openapi.json` (versionado, JSON con claves ordenadas). `npm run gen:api` genera `frontend/types/api.ts` desde ese archivo. **La CI regenera ambos y falla si `git diff` no está vacío**: el job backend comprueba `openapi.json` y el frontend, `api.ts`. | Cada job sigue siendo independiente y el `openapi.json` versionado deja el contrato visible en las PR. |
| D19 | `structlog` con salida JSON en la CLI de ingesta (instrumento, timeframe, rango, velas recibidas y velas escritas). | Trazabilidad que pide `tech-stack.md`. |
| D20 | Fixture de tests `db`: antes de cada test se hace `TRUNCATE` de `ohlcv_bars` y `trade_signals`. `instruments` se conserva (viene del seed). | Tests aislados sin rehacer las migraciones. |
| D21 *(implementación)* | `upsert_candles` hace `flush` implícito (ejecuta el `INSERT … ON CONFLICT`) pero **no hace `commit`**: lo decide quien llama. El servicio de ingesta (`_ingest`) hace el `commit` tras cada instrumento y timeframe. | Los tests del repositorio pueden hacer `rollback`, y la ingesta confirma cada unidad de trabajo completa. |
| D22 *(implementación)* | `fetch_latest(session, instrument_id, timeframe, limit, symbol)` recibe también `symbol`. | La tabla guarda `instrument_id`, no el símbolo, y `CandleSchema` lo exige; así se evita un `JOIN` o una segunda consulta. |
| D23 *(implementación)* | OANDA se pagina con `from` + `count=5000` (`PAGE_COUNT`), avanzando el cursor secuencialmente, sin usar `from`+`to` juntos. | OANDA no admite `count` junto a `from` y `to`; con `from`+`count` se controla el tamaño de página (máximo 5000). |
| D24 *(implementación)* | Los adaptadores son de **un solo uso**: `fetch_ohlcv` libera sus conexiones (`aclose` del cliente httpx o cierre del exchange de ccxt) al terminar, y el registro crea uno nuevo por cada ingesta. | Evita conexiones abiertas y estado compartido; el ciclo de vida queda dentro de la llamada. |
| D25 *(implementación)* | Las columnas `NUMERIC` devuelven los `Decimal` **rellenos con ceros** según la escala de la columna. Se compara por valor (`Decimal(x) == Decimal("90.00000001")`), no por cadena. | Comportamiento de Postgres; el valor exacto no cambia, solo la representación (el test de la API lo contempla). |
| D26 *(implementación)* | La BD de test debe estar **migrada a `head` antes de `pytest`** (`DATABASE_URL="$TEST_DATABASE_URL" uv run alembic upgrade head`). La fixture `db_session` solo hace `TRUNCATE`, no migra. La CI ya lo hace en el paso «Migraciones (dev y test)». | Los tests `db` dependen del esquema y del seed; sin migrar, fallan. |
| D27 *(implementación)* | Contraste con `exchangeInfo` de Binance (grupo 4): `tick_size = 0.01` y `lot_size = 0.00001` de BTC/USDT **coinciden** con la migración `0002`, que no se modificó. | Cierra el riesgo «valores de tick y lote» para Binance; OANDA sigue pendiente. Nota: el contraste se anota según el registro del grupo 4; aquí solo se verificó que la migración contiene esos valores. |

## 4. Variables de entorno (backend, nuevas)

```dotenv
OANDA_API_TOKEN=            # opcional hasta tener cuenta practice
OANDA_ACCOUNT_ID=           # opcional
OANDA_BASE_URL=https://api-fxpractice.oanda.com
```

`OANDA_API_TOKEN` es `SecretStr | None` y nunca aparece en logs. Se añaden también a `backend/.env.example`.

## 5. Contexto, tono y patrones a seguir

- **Sin texto de UI en esta fase.** El texto visible es el de los mensajes de error de la API (`detail`) y la salida de la CLI. Van en **español**, son técnicos y concretos (p. ej. `"Instrumento desconocido: XYZ"`) y no esconden fallos: si la ingesta no descarga nada, lo dice.
- **Esquemas primero:** cada grupo del plan escribe el esquema o el protocolo antes que la implementación, y los tests antes o junto a ella.
- **Patrones existentes:**
  - Sesión con `get_session` de [`app/core/db.py`](../../backend/app/core/db.py).
  - Configuración con `get_settings()`.
  - Tests de base de datos con `@pytest.mark.db` y la fixture `use_test_db` de [`tests/conftest.py`](../../backend/tests/conftest.py).
  - Router montado en `api_router` (`/api/v1`).
- **`mypy --strict` sobre todo `app/`.** Si ccxt no trae tipos suficientes, se aísla en el adaptador con un `override` de mypy para el módulo `ccxt.*`, nunca con `Any` repartido por el código.
- **Fuente de verdad:** si esta spec contradice `tech-stack.md`, prevalece `tech-stack.md`.

## 6. Preguntas abiertas y riesgos

| Tema | Estado | Qué hacer |
| :--- | :--- | :--- |
| Cuenta OANDA practice | **Pendiente.** | Cuando exista: lanzar un backfill corto de los 3 instrumentos OANDA, contrastar `tick_size`/`lot_size` con `/instruments` y, si cambian, crear una migración de datos. Se anota en esta tabla. |
| Valores de tick y lote | Binance contrastado (D27); OANDA provisional. | OANDA: contrastar cuando exista la cuenta practice. |
| Huecos de datos | Se aceptan. | Los fines de semana de FX y las pausas diarias de NAS100 son huecos legítimos. La detección de huecos anómalos queda para después. |
| Límites de tasa | Mitigados. | ccxt con `enableRateLimit=True`; OANDA, máximo 5000 velas por petición y paginación secuencial. |
| Versión de TimescaleDB en CI (`latest`) y en local | Riesgo bajo. | Se usa `create_hypertable('ohlcv_bars', 'ts', chunk_time_interval => INTERVAL '30 days')`, compatible con 2.x. |
