# Plan — Fase 1: Datos y esquemas

Grupos de tareas en orden de ejecución. Cada grupo termina en un **commit verde** (ruff, mypy y pytest pasan) y se puede implementar y revisar por separado. Las decisiones (D1–D20) están en [`requirements.md`](requirements.md).

Regla de cada grupo: **esquema o protocolo → tests → implementación**.

---

## 1. Dependencias y configuración

1.1. `uv add ccxt structlog httpx` (`httpx` pasa de dev a runtime) y comprobar que `uv.lock` se actualiza (D10).
1.2. `Settings`: añadir `oanda_api_token: SecretStr | None`, `oanda_account_id: str | None`, `oanda_base_url` (por defecto, la URL de practice) y los horizontes de backfill (D17). Actualizar `backend/.env.example`.
1.3. Si hace falta, `override` de mypy para `ccxt.*` en `pyproject.toml`.
1.4. `app/core/logging.py`: configuración de structlog en JSON (D19).
1.5. Tests: `test_config.py` cubre los valores por defecto nuevos y que el token no aparece en `repr(settings)`.
1.6. Commit: `chore(backend): dependencias y settings de la fase 1`.

## 2. Esquemas de dominio (1.1)

2.1. `app/schemas/enums.py`: `AssetClass`, `Provider`, `Timeframe` (con `duration` y `floor(dt)`), `Direction`, `SignalStatus` y `SessionType`.
2.2. `app/schemas/instrument.py`: `InstrumentSchema` (`frozen`, `tick_size` y `lot_size` `Decimal > 0`).
2.3. `app/schemas/candle.py`: `CandleSchema` con sus validadores (zona horaria obligatoria y normalización a UTC, alineación con el timeframe, coherencia OHLC y volumen ≥ 0).
2.4. Tests (`tests/schemas/`):
   - Velas válidas en los 4 timeframes.
   - Rechazo de `ts` *naive*, de `ts` desalineado, de `high < close`, de `low > open`, de precios ≤ 0 y de volumen negativo.
   - Un `ts` con offset `+02:00` se normaliza a UTC.
   - Los `Decimal` se serializan como cadena en `model_dump(mode="json")`.
   - Los valores de los enums coinciden con los de la spec.
2.5. Commit: `feat(backend): esquemas de dominio (enums, instrumento, vela)`.

## 3. Base de datos (1.2, 1.3, 1.4)

3.1. `app/models/instrument.py`, `ohlcv_bar.py` y `trade_signal.py` (SQLAlchemy 2.0, `Mapped[...]`), con los `CHECK` de enum (D7) y de coherencia OHLC. Registrarlos en `app/models/__init__.py` para que `env.py` los vea.
3.2. Migración `0002_instruments`: tabla y seed de los 4 instrumentos (D8).
3.3. Migración `0003_ohlcv_bars`: tabla, PK compuesta y `create_hypertable` con chunks de 30 días. El `downgrade` elimina la tabla.
3.4. Migración `0004_trade_signals`: tabla con `id` `uuid_generate_v4()`, `status` por defecto `PENDING` e índice `(status, created_at)`.
3.5. `app/repositories/ohlcv.py`: `upsert_candles(session, instrument_id, candles) -> int` (D9, por lotes de 1000, devuelve las filas insertadas o actualizadas), `latest_ts(...)` y `fetch_latest(..., limit)`.
3.6. `app/repositories/instruments.py`: `get_by_symbol`, `list_all` y la conversión a `InstrumentSchema`.
3.7. Fixture `db_session` en `conftest.py`: sesión contra `TEST_DATABASE_URL` con `TRUNCATE` previo de `ohlcv_bars` y `trade_signals` (D20).
3.8. Tests `db`:
   - El seed deja exactamente los 4 instrumentos con los valores de la tabla de requisitos.
   - `ohlcv_bars` es hypertable (consulta a `timescaledb_information.hypertables`).
   - Upsert idempotente: dos ejecuciones con las mismas velas → mismo número de filas y 0 actualizadas la segunda vez.
   - Una vela corregida se actualiza.
   - El `CHECK` de OHLC rechaza una fila incoherente insertada a mano.
   - Un `trade_signal` nuevo nace `PENDING` y un `status` desconocido se rechaza.
   - `alembic downgrade base` seguido de `upgrade head` funciona.
3.9. Commit: `feat(backend): modelos instruments, ohlcv_bars y trade_signals`.

## 4. Adaptadores de datos de mercado (1.5, 1.6, 1.7)

4.1. `app/market_data/base.py`: `MarketDataAdapter` (Protocol, D14), `MarketDataError` y el helper `drop_open_candle(candles, tf, now)` (D5).
4.2. `app/market_data/fake.py`: `FakeAdapter` determinista. Genera velas válidas y alineadas a partir de una semilla y respeta `start`, `end` y la regla de velas cerradas.
4.3. `app/market_data/ccxt_adapter.py`: `CcxtAdapter(exchange)`, al que se le inyecta el exchange (en producción, `ccxt.async_support.binance` con `enableRateLimit=True`):
   - Paginación por `since` y `limit=1000` hasta `end`.
   - Conversión con `Decimal(str(x))` (D4) y de milisegundos a UTC.
   - Deduplicación y descarte de la vela abierta.
   - Cierre del exchange (`close()`) al terminar.
4.4. Contrastar `tick_size` y `lot_size` de BTC/USDT con `exchangeInfo`. Si difieren, corregir la migración `0002` (aún no integrada).
4.5. `app/market_data/oanda.py`: `OandaAdapter(client: httpx.AsyncClient, settings)`:
   - `GET /v3/instruments/{provider_symbol}/candles` con `price=M`, la `granularity` mapeada (`M15`, `H1`, `H4`, `D`), `alignmentTimezone=UTC`, `dailyAlignment=0` (D6) y como máximo 5000 velas por página.
   - Solo `complete: true`.
   - Mapeo de `mid.o/h/l/c` a `Decimal` desde la cadena y de `volume` como volumen de ticks (D13).
   - Errores HTTP → `MarketDataError` con estado y mensaje; sin token → `MarketDataError("Falta OANDA_API_TOKEN")` (D12).
4.6. `app/market_data/registry.py`: `adapter_for(instrument) -> MarketDataAdapter` según `provider`.
4.7. Fixtures en `tests/fixtures/`:
   - `binance_btcusdt_1h_page1.json` y `page2.json`, con formato de lista de listas de ccxt; la última vela de la página 2 está abierta.
   - `oanda_eurusd_h1.json`, `oanda_xauusd_d.json` y `oanda_nas100_m15.json`, con formato v20; incluyen una vela `complete: false` y un hueco de fin de semana.
4.8. Tests (sin red):
   - `FakeAdapter` es determinista.
   - ccxt pagina, deduplica, descarta la vela abierta y convierte a `Decimal` exacto (`"0.1"` y no `0.1000000000000000055…`).
   - OANDA construye la URL y los *query params* esperados (se verifican en el `MockTransport`), descarta las velas incompletas y alinea las diarias a 00:00 UTC.
   - Un 401 se convierte en `MarketDataError`.
   - Sin token, se produce el error claro.
4.9. Commit: `feat(backend): MarketDataAdapter, adaptadores fake, ccxt y OANDA`.

## 5. Servicio de ingesta y CLI (1.8)

5.1. `app/services/ingestion.py`:
   - `backfill(session, adapter, instrument, tf, since, until=None, now) -> IngestResult`.
   - `incremental(session, adapter, instrument, tf, now) -> IngestResult` (D16).
   - `IngestResult` es un esquema Pydantic con `symbol`, `timeframe`, `fetched`, `written`, `first_ts` y `last_ts`.
5.2. `app/cli/ingest.py` (`argparse`, D15): subcomandos `backfill` e `incremental`, con `--symbol`, `--tf`, `--since` y `--all`. Registra con structlog y devuelve un *exit code* ≠ 0 si algún instrumento falla, pero procesa el resto.
5.3. Tests `db` con `FakeAdapter`:
   - El backfill escribe N velas.
   - Repetirlo escribe 0.
   - El incremental solo trae lo nuevo y re-pide la última vela.
   - El incremental sin datos cae al backfill por defecto.
   - `--all` recorre los 4 instrumentos × 4 timeframes.
   - Un adaptador que falla en un instrumento no impide procesar los demás y el *exit code* es 1.
5.4. Smoke manual: backfill real de BTC/USDT `1h` con un `--since` de unos días (véase la validación).
5.5. Commit: `feat(backend): servicio y CLI de ingesta OHLCV`.

## 6. Endpoint y tipos generados (1.9)

6.1. `app/api/v1/market.py`: `GET /market/ohlcv` con `response_model=list[CandleSchema]` y los parámetros validados con `Query` (`limit` entre 1 y 5000). Devuelve 404 con `detail` en español si el símbolo no existe. Montarlo en `router.py`.
6.2. `backend/scripts/export_openapi.py`: escribe `backend/openapi.json` con `sort_keys=True` y salto de línea final (D18).
6.3. Frontend:
   - `npm i -D openapi-typescript`.
   - Script `"gen:api": "openapi-typescript ../backend/openapi.json -o types/api.ts"`.
   - Generar `frontend/types/api.ts` y excluirlo de ESLint si hace falta.
6.4. Test de Vitest (`types/api.test.ts`): comprobación de tipos con `expectTypeOf` de que `paths["/api/v1/market/ohlcv"]["get"]` devuelve un array de `CandleSchema` con `open: string`.
6.5. Tests de pytest:
   - 200 con datos sembrados por `FakeAdapter`, en orden ascendente y con exactamente `limit` velas.
   - Lista vacía cuando no hay velas.
   - 404 si el símbolo es desconocido.
   - 422 si `tf` no es válido y si `limit` vale 0 o 5001.
   - Los precios salen como cadena con la precisión intacta.
   - `export_openapi` es determinista: dos ejecuciones dan el mismo archivo.
6.6. Commit: `feat: GET /market/ohlcv y tipos TS generados con openapi-typescript`.

## 7. CI, documentación y cierre (incluye 0.4)

7.1. `ci.yml`, job backend: paso `uv run python scripts/export_openapi.py && git diff --exit-code openapi.json`.
7.2. `ci.yml`, job frontend: paso `npm run gen:api && git diff --exit-code types/api.ts`, antes de `typecheck`.
7.3. README: sección de ingesta (comandos de la CLI), `gen:api` como comando real y estructura actualizada (`market_data/`, `services/`, `cli/`, `repositories/`, `types/api.ts`).
7.4. `tech-stack.md`: changelog con las dependencias añadidas, `Decimal`/`NUMERIC` y el contrato `openapi.json` versionado.
7.5. Hacer push de la rama, abrir la PR y conseguir la CI en verde (cubre la parte de PR de 0.4).
7.6. Tras el merge, comprobar que la CI en `main` está en verde y marcar **0.4 y 1.1–1.9** como `[x]` en `roadmap.md`.
7.7. Registrar en `requirements.md` las decisiones tomadas durante la implementación (D21 en adelante, con la marca *(implementación)*).
