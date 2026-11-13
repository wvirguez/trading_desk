# Roadmap — QuantAgentic Terminal (MVP)

> Orden de implementación de alto nivel, derivado de `TODO.md`. Cada fase es **pequeña**, se entrega funcionando y tiene un criterio de *hecho* verificable. No se empieza una fase sin haber cerrado la anterior.
> Cada fase sigue el ciclo SDD: **spec → esquema (Pydantic) → tests → implementación → tipos TS regenerados**.

Leyenda: `[ ]` pendiente · `[x]` hecha

---

## Bloque 0 — Cimientos del repositorio

- [x] **0.1 Reestructurar el monorepo.** Mover la app Next.js a `frontend/` y crear `backend/` con `uv init`. *Hecho:* `npm run dev` (frontend) y `uv run python -c "import app"` (backend) funcionan.
- [x] **0.2 Esqueleto FastAPI.** Crear `app/main.py`, `core/config.py` (pydantic-settings) y `GET /api/v1/health`. *Hecho:* un test de health en pytest pasa.
- [x] **0.3 Tooling de calidad.** Configurar ruff, mypy, pytest, Vitest y ESLint. *Hecho:* los comandos `lint` y `test` pasan en vacío en ambos lados.
- [x] **0.4 CI mínima.** Workflow de GitHub Actions con lint, typecheck y tests para backend y frontend. *Hecho:* CI en verde en `main`.
- [x] **0.5 Base de datos local.** Postgres 16 + TimescaleDB + `uuid-ossp`, con la sesión async de SQLAlchemy y Alembic inicializado. *Hecho:* `alembic upgrade head` funciona sobre una base de datos vacía.

## Fase 1 — Datos y esquemas *(TODO: Week 1)*

- [x] **1.1 Esquemas de dominio.** Enums (`AssetClass`, `Timeframe`, `Direction`, `SignalStatus`), `InstrumentSchema` y `CandleSchema`. *Hecho:* tests de validación de los esquemas.
- [x] **1.2 Modelo `instruments`.** Modelo, migración y seed de los 4 instrumentos (BTC/USDT, EUR/USD, XAU/USD, NAS100) con tick size, lot size y sesión.
- [x] **1.3 Modelo `ohlcv_bars`.** Hypertable de Timescale con clave única `(instrument_id, timeframe, ts)` y upsert idempotente.
- [x] **1.4 Modelo `trade_signals`.** Tabla de señales y migración (estados `PENDING`/`APPROVED`/`REJECTED`/`EXECUTED`).
- [x] **1.5 Interfaz `MarketDataAdapter`.** Protocolo común y normalización a `CandleSchema` en UTC, con un adaptador *fake* para tests.
- [x] **1.6 Adaptador ccxt (cripto).** OHLCV histórico paginado de BTC/USDT. *Hecho:* test con respuestas grabadas.
- [x] **1.7 Adaptador OANDA (FX + índices).** EUR/USD, XAU/USD y NAS100_USD contra la cuenta practice. *Hecho:* test con respuestas grabadas. *Nota (2026-11-13):* sin cuenta OANDA, los datos reales de FX, XAU/USD (`GC=F`) y NAS100 vienen provisionalmente de Yahoo (`yfinance`); ver `specs/2026-11-13-proveedor-yahoo/`. Pendiente: proveedor fiable.
- [x] **1.8 Servicio de ingesta.** Backfill e ingesta incremental por instrumento y timeframe, ejecutables con un comando CLI.
- [x] **1.9 Endpoint `GET /market/ohlcv`.** Recibe `symbol`, `tf` y `limit`, devuelve `List[CandleSchema]` y genera el primer `openapi-typescript`. *Hecho:* los tipos TS se generan y la CI comprueba que están actualizados.

## Fase 2 — Motor cuantitativo y núcleo de riesgo determinista *(TODO: Week 2)*

- [ ] **2.1 Features básicas.** Rendimientos logarítmicos, volatilidad móvil y ATR (polars). *Hecho:* tests contra valores de referencia.
- [ ] **2.2 Estadísticos de régimen.** Z-score, exponente de Hurst y test ADF. *Hecho:* tests con series sintéticas (random walk, serie con reversión a la media y serie con tendencia).
- [ ] **2.3 Estructura de mercado determinista.** Swings, BOS, CHoCH y detección de FVG. *Hecho:* fixtures de velas con resultados esperados.
- [ ] **2.4 Clasificador de régimen.** `MEAN_REVERTING`, `TRENDING` y `HIGH_VOLATILITY_NOISE` a partir de 2.1–2.2.
- [ ] **2.5 Position sizing.** Tamaño a partir del riesgo %, la distancia al stop, el tick size y el lot size del instrumento. *Hecho:* tests de propiedades con hypothesis (nunca se supera el 1 %).
- [ ] **2.6 Kelly fraccional y riesgo de ruina.** Fórmulas puras con límites. *Hecho:* tests de propiedades.
- [ ] **2.7 Guardas de cartera.** Pérdida diaria del 3 %, exposición abierta y matriz de correlación, con veto por R:R < 1,8.
- [ ] **2.8 Backtester vectorizado.** `BacktestConfig` → `BacktestMetricsSchema` (Sharpe, max drawdown, win rate, expectancy, curva de capital).
- [ ] **2.9 Tests golden de determinismo.** Datasets fijos versionados con métricas exactas esperadas.
- [ ] **2.10 Endpoint `POST /quant/backtest`** y modelo `strategies` (parámetros en JSONB y métricas).

## Fase 3 — Orquestación multiagente *(TODO: Week 3)*

- [ ] **3.1 Esquemas de salida de agentes.** `MarketStructureReport`, `QuantAlphaReport`, `RiskVerdict` y `TradeSignalSchema` canónico.
- [ ] **3.2 Modelo `agent_analyses`.** Solo inserción, con traza JSONB, modelo, tokens, coste y latencia.
- [ ] **3.3 Cliente PydanticAI + Claude.** Configuración del modelo y `TestModel` para la CI. *Hecho:* un agente "eco" con salida tipada pasa los tests.
- [ ] **3.4 `MarketStructureAgent`.** Herramientas deterministas (2.3) más síntesis multi-timeframe (15m, 1H, 4H, 1D).
- [ ] **3.5 `QuantAlphaAgent`.** Herramientas 2.1, 2.2, 2.4 y 2.6, con interpretación del régimen.
- [ ] **3.6 Construcción de la señal propuesta.** Combina 3.4 y 3.5 en una propuesta de entrada, SL y TP. El tamaño de posición lo calcula siempre 2.5, nunca el LLM.
- [ ] **3.7 Veto determinista + `RiskAuditorAgent`.** Primero se aplican las guardas 2.7 en código y después el agente emite APPROVE/VETO con su justificación.
- [ ] **3.8 Orquestador.** Pipeline async con persistencia de cada paso en `agent_analyses` y de la señal resultante en `trade_signals`.
- [ ] **3.9 `POST /agents/analyze` con SSE.** Stream de eventos por paso más el `AgentReportSchema` final.
- [ ] **3.10 `GET /signals/active`.** Señales aprobadas filtrables por `asset_class`.

## Fase 4 — Terminal UI en Next.js *(TODO: Week 4)*

- [ ] **4.1 Layout del terminal.** Shell oscuro, navegación (`/desk`, `/backtest`, `/agents`, `/journal`), store Zustand (símbolo y timeframe activos) y providers de TanStack Query.
- [ ] **4.2 Gráfico de velas.** Wrapper de `lightweight-charts` alimentado por `GET /market/ohlcv`, con selector de símbolo y timeframe.
- [ ] **4.3 Overlays de señal.** Zona de entrada, SL, TP y cajas FVG dibujadas a partir de `TradeSignalSchema`.
- [ ] **4.4 WebSocket `/ws/stream/{symbol}`.** Backend: `TickUpdateEvent` y `SignalAlertEvent`. Frontend: hook que actualiza la última vela.
- [ ] **4.5 Feed de razonamiento de agentes.** Consume el SSE de `/agents/analyze` y muestra la traza paso a paso.
- [ ] **4.6 Paper trading: backend.** `POST /signals/{id}/execute` (simulado), `OrderReceiptSchema` y simulador de fills contra OHLCV.
- [ ] **4.7 Blotter de ejecución.** Tabla de órdenes y posiciones simuladas, con su PnL.
- [ ] **4.8 Vista de backtest.** Formulario `BacktestConfig`, curva de capital y métricas.
- [ ] **4.9 Journal.** Comparación entre señales emitidas y resultado simulado (base del criterio de éxito del MVP).
- [ ] **4.10 E2E con Playwright.** Flujo completo: analizar → ver señal en el gráfico → ejecutar en paper → verla en el blotter.

---

## Post-MVP (no planificado)

- `MacroSentimentAgent`.
- Ejecución en testnet o demo y, después, con capital real y HITL.
- Agregados continuos y compresión de Timescale.
- Docker Compose y observabilidad de LLM (Logfire/Langfuse).
- Datos de orderbook y análisis de flujo de órdenes.
