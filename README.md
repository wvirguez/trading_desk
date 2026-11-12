# ⚡ QuantAgentic Terminal — Plataforma de trading cuantitativo y algorítmico impulsada por IA (MVP)

> **Terminal personal de investigación cuantitativa multi-activo**, potenciado por agentes de IA, backtesting vectorizado determinista y desarrollo dirigido por especificaciones (SDD).
>
> **Alcance del MVP:** BTC/USDT (cripto) • EUR/USD y XAU/USD (Forex) • NAS100 (índices) — en marcos temporales de 15m, 1H, 4H y 1D, **solo en paper trading**.

📜 **La fuente única de verdad del proyecto es [`specs/`](specs/):**

- [`specs/mission.md`](specs/mission.md): misión, público objetivo, alcance y principios no negociables.
- [`specs/tech-stack.md`](specs/tech-stack.md): decisiones tecnológicas cerradas.
- [`specs/roadmap.md`](specs/roadmap.md): orden de implementación en fases pequeñas.

Si este README contradice a `specs/`, prevalece `specs/`.

---

## 🏗 Visión y arquitectura del sistema

**QuantAgentic Terminal** es una herramienta personal para un trader-desarrollador. En lugar de depender de alertas basadas en indicadores estáticos, la plataforma emplea **agentes de IA** especializados que analizan datos de mercado en varios marcos temporales, interpretan la estructura y el régimen del mercado y formulan **propuestas de operación** (`TradeSignalSchema`) estrictamente tipadas. Antes de llegar al usuario, cada propuesta pasa por controles de riesgo deterministas.

El objetivo del MVP es responder con rigor a una pregunta: *¿producen los agentes señales con valor esperado positivo, y puedo auditar por qué las produjeron?*

```mermaid
graph TD
subgraph Frontend ["Frontend (Next.js 16 App Router)"]
UI[TradingView Lightweight Charts + Panel cuantitativo]
AgentChat[Feed de razonamiento de agentes]
State[Zustand + TanStack Query + Cliente WebSocket]
end

subgraph Backend ["Backend (FastAPI + Uvicorn)"]
API[Pasarela REST, SSE y WebSocket]
Orch[Orquestador async de agentes]
QuantEngine[Motor cuantitativo y backtester vectorizado]
RiskEngine[Motor de riesgo y dimensionamiento de posiciones]
PaperBroker[Simulador de paper trading]
end

subgraph Agents ["Agentes PydanticAI + Anthropic Claude"]
A1[MarketStructureAgent]
A2[QuantAlphaAgent]
A4[RiskAuditorAgent]
end

subgraph Feeds ["Datos de mercado"]
CCXT[ccxt / Binance]
OANDA[OANDA v20 practice]
end

subgraph Storage ["Persistencia local"]
PG[(PostgreSQL 16 + TimescaleDB + JSONB)]
end

UI <-->|WebSocket / REST| API
AgentChat <-->|SSE| API
API --> Orch
Orch <--> A1 & A2 & A4
A1 & A2 <--> QuantEngine
A4 <--> RiskEngine
API --> PaperBroker
Feeds --> Backend
Backend <-->|SQLAlchemy Async + asyncpg| PG
```

> El `MacroSentimentAgent` (análisis macro y de sentimiento) queda fuera del MVP; está previsto para después.

---

## 🛠 Stack tecnológico

Resumen. El detalle completo está en [`specs/tech-stack.md`](specs/tech-stack.md).

| Capa | Tecnología | Propósito |
| :--- | :--- | :--- |
| **Frontend** | **Next.js 16.4 (App Router)**, React 19.3, TypeScript 5, Tailwind CSS 4, npm | Interfaz de terminal reactiva y densa. |
| **Gráficos e interfaz** | `lightweight-charts` (TradingView), shadcn/ui, Lucide | Velas OHLCV, zonas de entrada, SL/TP, cajas FVG y curvas de capital. |
| **Estado y tiempo real** | Zustand, TanStack Query, WebSocket, SSE | Estado del terminal, caché de servidor y streaming. |
| **Contratos** | Pydantic v2 → OpenAPI → `openapi-typescript` | Los tipos TS se **generan**; no se escriben a mano. |
| **API del backend** | **FastAPI**, **Uvicorn**, Pydantic v2, Python 3.11+ con **uv** | Endpoints async, validación estricta, SSE y WebSocket. |
| **Capa de agentes** | **PydanticAI** + **Anthropic Claude** (`claude-sonnet-5-5` por defecto) | Salidas estructuradas y herramientas deterministas; orquestador async propio. |
| **Núcleo cuantitativo** | `polars`, `numpy`, `scipy`, `statsmodels`, **backtester vectorizado propio** | ATR, estructura de mercado, Z-score, Hurst, ADF y métricas de backtest reproducibles. |
| **Datos de mercado** | `ccxt` (BTC/USDT) y **OANDA v20 practice** (EUR/USD, XAU/USD, NAS100_USD) | Ingesta unificada de OHLCV normalizado en UTC. |
| **Base de datos** | **PostgreSQL 16+** local con **TimescaleDB**, SQLAlchemy 2.0 async, Alembic | Hypertable OHLCV, señales, estrategias y auditoría de agentes en JSONB. |
| **Calidad** | ruff, mypy, pytest + hypothesis, ESLint, Vitest, Playwright, GitHub Actions | Tests de determinismo, propiedades de riesgo y E2E. |

---

## 📜 Contratos SDD (desarrollo dirigido por especificaciones)

Todas las funcionalidades se desarrollan con el enfoque **«esquemas primero»**: no se implementa ningún endpoint, herramienta de agente ni componente de UI sin haber definido antes su contrato Pydantic. Los tipos TypeScript se generan a partir de ese contrato.

### Dominio y esquema de base de datos (`quant_terminal_db`)

| Tabla | Contenido |
| :--- | :--- |
| `instruments` | Registro normalizado de activos: símbolo, clase de activo (`CRYPTO`, `FOREX`, `INDEX`), tamaño del tick, tamaño del lote y horario de sesión. |
| `ohlcv_bars` | **Hypertable de TimescaleDB**: `instrument_id`, `timeframe`, `ts`, `open`, `high`, `low`, `close`, `volume`. Clave única `(instrument_id, timeframe, ts)`. |
| `agent_analyses` | Registro de auditoría **de solo inserción** de cada ejecución de agente: `id`, `instrument_id`, `timeframe`, régimen, puntuación de confianza, traza de razonamiento (JSONB), modelo, tokens, coste, latencia y `created_at`. |
| `strategies` | Reglas algorítmicas parametrizadas: `id`, nombre, clase de activo, parámetros (JSONB), Sharpe, máximo drawdown y tasa de aciertos. |
| `trade_signals` | Señales validadas por el motor de riesgo: `id`, `strategy_id`, `analysis_id`, dirección (`LONG`/`SHORT`), entrada, SL, TP, R:R, tamaño de posición y estado (`PENDING`, `APPROVED`, `REJECTED`, `EXECUTED`). |

### Orquestación multiagente

Pipeline async secuencial: **Structure → Quant → veto determinista → RiskAuditor**. Cada agente devuelve un esquema Pydantic estricto.

1. **`MarketStructureAgent`**
   - *Entradas:* OHLCV en 15m, 1H, 4H y 1D, ATR y perfil de volumen.
   - *Salidas:* sesgo de tendencia, BOS, CHoCH, FVG y niveles clave de liquidez. La detección la hacen herramientas deterministas; el LLM sintetiza el resultado.
2. **`QuantAlphaAgent`**
   - *Entradas:* rendimientos logarítmicos, volatilidad móvil (σ), exponente de Hurst (H) y test ADF.
   - *Salidas:* régimen (`MEAN_REVERTING`, `TRENDING`, `HIGH_VOLATILITY_NOISE`) y Z-scores extremos. La fracción de Kelly (f\*) la calcula el código, no el LLM.
3. **Veto determinista (código):** rechaza automáticamente cualquier propuesta con **R:R < 1,8** o que haga superar los límites de riesgo o drawdown de la cartera.
4. **`RiskAuditorAgent`**
   - *Entradas:* propuesta, saldo de la cuenta, exposición abierta y matriz de correlación.
   - *Salidas:* veredicto final `APPROVE`/`VETO` con su justificación.

### API REST, SSE y WebSocket (`/api/v1`)

| Método | Endpoint | Descripción | Solicitud → respuesta |
| :--- | :--- | :--- | :--- |
| `GET` | `/market/ohlcv` | Velas históricas normalizadas | `symbol`, `tf`, `limit` → `List[CandleSchema]` |
| `POST` | `/agents/analyze` | Análisis multiagente | `AnalyzeRequest` → stream SSE + `AgentReportSchema` |
| `POST` | `/quant/backtest` | Simulación vectorizada de una estrategia | `BacktestConfig` → `BacktestMetricsSchema` |
| `GET` | `/signals/active` | Señales aprobadas por el sistema de riesgo | `asset_class` → `List[TradeSignalSchema]` |
| `POST` | `/signals/{id}/execute` | Ejecución **simulada** (paper trading) | `ExecutionConfirm` → `OrderReceiptSchema` |
| `WS` | `/ws/stream/{symbol}` | Ticks y alertas en tiempo real | `TickUpdateEvent` \| `SignalAlertEvent` |

### Esquema canónico `TradeSignalSchema`

```json
{
  "signal_id": "uuid-v4",
  "symbol": "XAUUSD",
  "asset_class": "FOREX",
  "timeframe": "1H",
  "regime": "TRENDING_BULLISH",
  "direction": "LONG",
  "entry_zone": [2642.50, 2645.00],
  "stop_loss": 2631.00,
  "take_profit_targets": [2665.00, 2682.00],
  "metrics": {
    "risk_reward_ratio": 2.45,
    "win_probability_est": 0.61,
    "expected_value_r": 1.10,
    "recommended_risk_pct": 1.0,
    "calculated_position_size": 0.85
  },
  "agent_consensus": {
    "technical_score": 88,
    "quant_score": 82,
    "risk_verdict": "APPROVED"
  }
}
```

---

## 📂 Estructura de directorios

> La estructura objetivo es un monorepo. Actualmente la app Next.js está en la raíz; pasarla a `frontend/` es el paso 0.1 del [roadmap](specs/roadmap.md).

```
trading_desk/
├── specs/                          # SDD: fuente única de verdad
│   ├── mission.md
│   ├── tech-stack.md
│   └── roadmap.md
│
├── backend/                        # FastAPI + motor cuantitativo + agentes
│   ├── app/
│   │   ├── api/v1/                 # Routers REST, SSE y WebSocket
│   │   ├── agents/                 # Agentes PydanticAI y orquestador
│   │   ├── quant/                  # Indicadores, Hurst, Z-score, backtester vectorizado
│   │   ├── data_feeds/             # Adaptadores ccxt (cripto) y OANDA (FX + índices)
│   │   ├── risk/                   # Position sizing, Kelly, correlación, guardas de drawdown
│   │   ├── paper/                  # Simulador de ejecución (paper trading)
│   │   ├── models/                 # Modelos ORM SQLAlchemy 2.0
│   │   ├── schemas/                # DTOs Pydantic v2 (contratos)
│   │   ├── core/                   # Config, sesión de BD, ciclo de vida
│   │   └── main.py                 # App FastAPI
│   ├── alembic/                    # Migraciones
│   ├── tests/                      # pytest: unitarios, propiedades y golden de backtest
│   ├── pyproject.toml
│   └── uv.lock
│
├── frontend/                       # Next.js 16 (App Router)
│   ├── app/                        # Rutas: /desk, /backtest, /agents, /journal
│   ├── components/
│   │   ├── charts/                 # Wrappers de lightweight-charts y overlays
│   │   ├── agents/                 # Feed de razonamiento
│   │   └── quant/                  # Curvas de capital, métricas, blotter
│   ├── hooks/                      # Hooks de WebSocket, SSE y TanStack Query
│   ├── types/api.ts                # GENERADO con openapi-typescript (no editar)
│   ├── store/                      # Estado Zustand (símbolo y timeframe activos)
│   ├── e2e/                        # Tests de Playwright
│   └── package.json
│
├── .github/workflows/              # CI: lint, typecheck y tests
├── AGENTS.md
└── README.md
```

---

## 🚀 Configuración del entorno de desarrollo local

### Requisitos previos

- Python 3.11+ con [**uv**](https://docs.astral.sh/uv/)
- Node.js 20+ con **npm**
- **PostgreSQL 16+** con la extensión **TimescaleDB**, en ejecución local en el puerto 5432
- Una cuenta **OANDA practice** (token de API y account ID)
- Una clave de API de **Anthropic**

### 1. Inicializar PostgreSQL local

```bash
psql -U postgres -c "CREATE USER quant_admin WITH PASSWORD 'quant_secret_dev';"
psql -U postgres -c "CREATE DATABASE quant_terminal_db OWNER quant_admin;"
psql -U postgres -d quant_terminal_db -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'
psql -U postgres -d quant_terminal_db -c 'CREATE EXTENSION IF NOT EXISTS timescaledb;'
```

### 2. Backend (FastAPI + Uvicorn)

```bash
cd backend
uv sync

cp .env.example .env
# Edita .env:
# DATABASE_URL=postgresql+asyncpg://quant_admin:quant_secret_dev@localhost:5432/quant_terminal_db
# ANTHROPIC_API_KEY=sk-ant-...
# LLM_MODEL=claude-sonnet-5-5
# OANDA_API_TOKEN=...
# OANDA_ACCOUNT_ID=...
# OANDA_ENV=practice

uv run alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Frontend (Next.js)

```bash
cd frontend
npm install

cp .env.local.example .env.local
# NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
# NEXT_PUBLIC_WS_URL=ws://localhost:8000/api/v1/ws

npm run gen:api   # Regenera types/api.ts desde el OpenAPI del backend
npm run dev
```

> ⚠️ Next.js 16 introduce cambios incompatibles con versiones anteriores. Antes de escribir código de frontend, consulta `node_modules/next/dist/docs/` (véase [`AGENTS.md`](AGENTS.md)).

### 4. Calidad y tests

```bash
# Backend
cd backend && uv run ruff check . && uv run mypy app && uv run pytest

# Frontend
cd frontend && npm run lint && npx tsc --noEmit && npx vitest run && npx playwright test
```

---

## 🛡 Salvaguardas de riesgo y ejecución

**Regla de oro:** un LLM nunca calcula el tamaño de la posición ni puede saltarse las reglas de gestión de riesgo.

- **Cálculos estrictamente deterministas:** los LLM se limitan a sintetizar patrones, interpretar el régimen de mercado y formular hipótesis. El tamaño de posición, la fracción de Kelly, el Sharpe, el drawdown y el R:R se calculan con Python puro (numpy, scipy, polars).
- **Veto determinista:** cualquier propuesta con R:R < 1,8 se rechaza en código, antes de que la vea el `RiskAuditorAgent`.
- **Circuit breakers:**
  - El riesgo máximo por operación es el **1,0 %** del capital (configurable).
  - La pérdida máxima diaria es el **3,0 %**. Al alcanzarla, la ejecución de señales se desactiva durante el resto del día.
- **Solo paper trading en el MVP:** no hay conexión con brokers para ejecutar órdenes reales. La ejecución con capital real, siempre con confirmación humana obligatoria (HITL), queda para después del MVP.
- **Auditabilidad:** cada análisis de agente se guarda de forma inmutable en `agent_analyses`.

---

## 🗺 Roadmap

El orden de implementación, en pasos pequeños con criterio de "hecho", está en [`specs/roadmap.md`](specs/roadmap.md). A grandes rasgos:

0. Cimientos del repositorio: monorepo, tooling, CI y base de datos.
1. Datos y esquemas: modelos, Timescale y adaptadores ccxt/OANDA.
2. Motor cuantitativo y núcleo de riesgo determinista.
3. Orquestación multiagente con PydanticAI y Claude.
4. Terminal UI en Next.js: gráfico, overlays, feed de agentes, blotter y journal.
