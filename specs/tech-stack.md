# Stack tecnológico — QuantAgentic Terminal

> Documento constitucional. Recoge las decisiones de tecnología **cerradas**. Cambiar una de ellas exige actualizar este archivo y su changelog.

## 1. Estructura del repositorio (monorepo)

```
trading_desk/
├── specs/        # Constitución y especificaciones SDD (fuente única de verdad)
├── backend/      # FastAPI + motor cuantitativo + agentes
├── frontend/     # Next.js 16 (App Router); se mueve aquí desde la raíz actual
└── .github/      # Workflows de CI
```

> **Desviación respecto al README:** el README menciona Next.js 15 y pnpm. El repositorio ya usa **Next.js 16.4 + React 19.3** con **npm** (`package-lock.json`). Prevalece lo que hay en el repositorio. Next 16 trae cambios incompatibles: antes de escribir código de frontend hay que consultar `node_modules/next/dist/docs/` (véase `AGENTS.md`).

## 2. Frontend

| Área | Elección | Notas |
| :--- | :--- | :--- |
| Framework | **Next.js 16.4** (App Router), React 19.3, TypeScript 5 | Rutas: `/desk`, `/backtest`, `/agents`, `/journal`. |
| Estilos | Tailwind CSS 4 + shadcn/ui + Lucide | Tema oscuro, alta densidad de información. |
| Gráficos | `lightweight-charts` (TradingView) | Velas OHLCV y overlays: zonas de entrada, SL/TP, cajas FVG y curvas de capital. |
| Estado | Zustand (estado del terminal) + TanStack Query (estado del servidor) | — |
| Tiempo real | WebSocket nativo (ticks/alertas) + SSE (stream de agentes) | — |
| Tipos de contrato | **`openapi-typescript`**, generado desde el `openapi.json` de FastAPI | Prohibido escribir tipos de API a mano. |
| Gestor de paquetes | npm | Node.js 22+ (LTS; Vitest 5 lo exige). |

## 3. Backend

| Área | Elección | Notas |
| :--- | :--- | :--- |
| Lenguaje | Python 3.12 | Fijado en `backend/.python-version` y gestionado por uv. |
| Gestor de entorno | **uv** (`pyproject.toml` + `uv.lock`) | Sustituye a `requirements.txt` del README. |
| API | FastAPI + Uvicorn (ASGI) + Pydantic v2 | Prefijo `/api/v1`. REST, SSE y WebSocket. |
| Configuración | `pydantic-settings` + `.env` | Secretos: `ANTHROPIC_API_KEY`, `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`, `DATABASE_URL`. |
| ORM / migraciones | SQLAlchemy 2.0 (async) + asyncpg + Alembic | — |
| Logging | `structlog` (JSON) | Correlación por `analysis_id`. |

## 4. Capa de agentes

| Área | Elección | Notas |
| :--- | :--- | :--- |
| Proveedor LLM | **Anthropic Claude** | Modelo por defecto: `claude-sonnet-5-5`; para el supervisor/auditor, opcionalmente `claude-opus-5-5`. Configurable por variable de entorno. |
| Framework | **PydanticAI** | Salidas tipadas con `output_type` de Pydantic y herramientas deterministas (`@agent.tool`). |
| Orquestación | Orquestador propio en Python async (secuencia: Structure → Quant → veto determinista → RiskAuditor) | Si hiciera falta un grafo con ciclos, se evaluaría `pydantic-graph`. LangGraph queda descartado para el MVP. |
| Testing de agentes | `TestModel` / `FunctionModel` de PydanticAI | Los tests de CI no llaman a la API real. |

## 5. Núcleo cuantitativo

| Área | Elección | Notas |
| :--- | :--- | :--- |
| DataFrames | **polars** | Pandas solo en las fronteras con librerías que lo exijan. |
| Numérico | numpy, scipy, statsmodels (ADF) | — |
| Backtester | **Motor vectorizado propio** (polars/numpy) | Se descarta vectorbt por su peso, su licencia y la falta de control del determinismo. |
| Riesgo | Módulo `risk/` en Python puro | Tamaño de posición, Kelly fraccional, riesgo de ruina, correlación y guardas de drawdown. |

## 6. Datos de mercado

| Mercado | Proveedor | Librería |
| :--- | :--- | :--- |
| Cripto (BTC/USDT) | Binance (datos públicos) | `ccxt` (async) |
| Forex (EUR/USD, XAU/USD) | **OANDA v20, cuenta practice** | `httpx` async contra la REST API v20 |
| Índices (NAS100) | **OANDA v20** (`NAS100_USD`) | Ídem |

Todos los adaptadores implementan una interfaz común (`MarketDataAdapter`) que devuelve `CandleSchema` normalizado en UTC.

## 7. Base de datos

| Área | Elección | Notas |
| :--- | :--- | :--- |
| Motor | **PostgreSQL 16**, local y nativo (puerto **5432**) | Sin Docker en local; en CI, *service* `timescale/timescaledb:latest-pg16`. Rol, BDs y extensiones con `backend/scripts/setup_db.sh`. |
| Series temporales | **TimescaleDB**: `ohlcv_bars` como hypertable | Compresión y agregados continuos, opcionales después del MVP. |
| Auditoría | Columnas JSONB en `agent_analyses` | Solo inserción: no se permiten `UPDATE` ni `DELETE`. |
| Extensiones | `uuid-ossp`, `timescaledb` | — |

## 8. Calidad, testing y CI

| Área | Backend | Frontend |
| :--- | :--- | :--- |
| Lint/format | `ruff` | ESLint 9 (`eslint-config-next`) |
| Tipado | `mypy --strict` en `quant/`, `risk/` y `schemas/` | `tsc --noEmit` |
| Unit tests | `pytest` + `pytest-asyncio`, `hypothesis` para propiedades de riesgo | **Vitest** + Testing Library |
| Determinismo | Tests *golden* de backtests sobre datasets fijos | — |
| E2E | — | **Playwright** (rutas críticas del terminal; se incorpora en la fase 4) |
| CI | **GitHub Actions**: lint → typecheck → tests (con un servicio Postgres+Timescale) → comprobación de que los tipos TS generados están actualizados | — |

## 9. Carencias conocidas y decisiones aplazadas

- **Contenedorización:** no hay Docker Compose por ahora. Se revisará si el entorno local da problemas.
- **Caché y colas:** no se usa Redis ni Celery. Las ingestas se programan con tareas asyncio o APScheduler.
- **Observabilidad de LLM:** el coste y los tokens se guardan en `agent_analyses`. Logfire o Langfuse quedan aplazados.
- **Datos de orderbook:** fuera del MVP.

## Changelog

- **2026-11-12:** versión inicial. Decisiones de la entrevista: monorepo, Claude + PydanticAI, OANDA para FX e índices, TimescaleDB, tipos generados con openapi-typescript, testing y CI.
- **2026-11-12 (Bloque 0):** Python fijado en 3.12; Node 22+ (Vitest 5); PostgreSQL 16 local en el puerto 5432 (el PG14 pasa al 5433, apagado); CI con *service* Timescale; Playwright aplazado a la fase 4.
- **2026-11-13 (Fase 1):** dependencias añadidas: `ccxt`, `structlog` y `httpx` (pasa de dev a runtime) en el backend, y `openapi-typescript` (dev) en el frontend. Precios y tamaños en `Decimal` (Pydantic) y `NUMERIC` (Postgres), nunca `float`; en JSON viajan como cadena. El contrato `backend/openapi.json` queda versionado y `frontend/types/api.ts` se genera con `npm run gen:api`; la CI falla si alguno de los dos no está al día.
