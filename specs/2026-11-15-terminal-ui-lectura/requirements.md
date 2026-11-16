# Requisitos — Fase 4 (parte 1): Terminal UI de lectura

- **Rama:** `phase-4-terminal-ui`
- **Roadmap:** pasos **4.1 – 4.5** de [`specs/roadmap.md`](../roadmap.md). Quedan para una segunda spec de la Fase 4 los pasos 4.6 – 4.9 y el E2E completo de 4.10 (véase «Fuera del alcance»).
- **Referencias:** [`mission.md`](../mission.md), [`tech-stack.md`](../tech-stack.md) y la spec anterior [`2026-11-15-orquestacion-multiagente`](../2026-11-15-orquestacion-multiagente/requirements.md) (las decisiones continúan en **D115**). Las fases 2 y 3 ya están cerradas (`[x]`) en el roadmap.

## 1. Contexto

La Fase 3 dejó un backend que produce señales auditables (`POST /agents/analyze` por SSE, `GET /signals/active`), pero el único frontend es la plantilla de `create-next-app`. El criterio de éxito de la misión *«El terminal muestra el gráfico con overlays, el feed de razonamiento en streaming y el blotter de paper trading»* necesita la UI. Esta spec construye la **mitad de lectura** del terminal: shell, gráfico de velas, overlays de señal y estructura, WebSocket de precio/alertas y el feed de razonamiento de los agentes. El paper trading (4.6/4.7) llega en la spec siguiente.

Cumple los principios de la misión: **1** (los tipos TS se generan desde OpenAPI; los esquemas de los eventos WebSocket y los nuevos endpoints nacen como esquemas Pydantic), **5** (el feed muestra la traza por paso, con modelo, tokens y latencia que ya persiste `agent_analyses`) y **2** (la UI no calcula riesgo ni tamaño: solo pinta lo que entrega el backend). Interfaz oscura, densa, técnica y en español (misión §2).

## 2. Alcance

### Dentro del alcance

1. **4.1 Layout del terminal.** Shell oscuro, navegación a `/desk`, `/backtest`, `/agents` y `/journal`, store Zustand (símbolo y timeframe activos) y providers de TanStack Query. `/backtest` y `/journal` son páginas marcadoras honestas («Pendiente: paso 4.8/4.9»).
2. **4.2 Gráfico de velas.** Envoltorio de `lightweight-charts` alimentado por `GET /market/ohlcv`, con selector de símbolo (desde un endpoint nuevo de instrumentos) y de timeframe.
3. **4.3 Overlays.** Zona de entrada, SL y TP a partir de `TradeSignalSchema` (`GET /signals/active`) y cajas FVG a partir de un endpoint determinista nuevo de estructura (D118).
4. **4.4 WebSocket `/api/v1/ws/stream/{symbol}`.** Backend: `TickUpdateEvent` y `SignalAlertEvent`. Frontend: hook que actualiza la última vela y avisa de señales nuevas.
5. **4.5 Feed de razonamiento.** Consume el SSE de `POST /agents/analyze` y muestra la traza paso a paso (`/agents` y panel lateral de `/desk`).
6. **E2E con Playwright** (decidido por el usuario): infraestructura y un flujo de lectura con la red simulada en el navegador (D124). El flujo completo de 4.10 (ejecutar en paper y ver el blotter) **no** se cierra aquí.
7. Infraestructura de apoyo: CORS en FastAPI, `GET /market/instruments` y `GET /market/structure`.

### Fuera del alcance

- 4.6 paper trading backend, 4.7 blotter, 4.8 vista de backtest, 4.9 journal y el E2E completo de 4.10 (ejecutar en paper → blotter). **El ítem 4.10 permanece `[ ]`.**
- Feed de ticks en tiempo real de un proveedor (D120): el WebSocket emite el último precio **ya ingerido**.
- Autenticación, multiusuario, i18n (solo español), tema claro, PWA y SSR de datos de mercado.
- Historial de análisis pasados en la UI (requeriría un endpoint que lea `agent_analyses`; va con el *journal*, 4.9).
- Ejecución de una señal desde la UI.

### Esquemas Pydantic (backend)

Todos inmutables (`frozen=True`). Precios en `Decimal` (en JSON viajan como cadena).

**`app/schemas/stream.py`** (nuevo):

| Esquema | Campos |
| :--- | :--- |
| `TickUpdateEvent` | `type: Literal["tick"]`, `symbol`, `timeframe`, `ts: datetime` (apertura de la vela a la que pertenece), `price: Decimal`, `provisional: bool` (siempre `true` mientras no haya feed real, D120) |
| `SignalAlertEvent` | `type: Literal["signal_alert"]`, `signal: TradeSignalSchema` (solo `APPROVED`) |
| `StreamErrorEvent` | `type: Literal["error"]`, `message: str` (español) |
| `StreamEvent` | unión discriminada por `type` de los tres anteriores; su envoltorio con nombre `StreamEventEnvelope` se publica en OpenAPI (D121) |

**Sin esquemas nuevos para los endpoints REST:** `GET /market/instruments` devuelve `list[InstrumentSchema]` y `GET /market/structure` devuelve `MarketStructureResult` (ya existen de las fases 1 y 2).

### Tablas

**Ninguna nueva.** No hay migraciones en esta spec.

### Endpoints (backend)

| Método y ruta | Cuerpo / parámetros | Respuesta |
| :--- | :--- | :--- |
| `GET /api/v1/market/instruments` | — | **200** `list[InstrumentSchema]` (orden de `id`) |
| `GET /api/v1/market/structure` | `symbol`, `tf`, `limit` (1–5000, 500 por defecto), `n` (ventana de swing, 1–10, 3 por defecto) | **200** `MarketStructureResult` calculado con `analyze_structure` (2.3) sobre las últimas `limit` velas; **404** `Instrumento desconocido: XYZ`; **422** `Datos insuficientes para <symbol> <tf>: N velas, se necesitan al menos M.` |
| `WS /api/v1/ws/stream/{symbol}` | query `tf: Timeframe` (obligatorio) | Mensajes JSON `StreamEvent`. Símbolo desconocido o `tf` inválido → cierre con código 1008 y motivo en español |

`/api/v1/ws/stream/{symbol}` lleva el prefijo `/api/v1` de `tech-stack.md` (el roadmap lo escribe sin prefijo). Como el símbolo canónico contiene `/` (p. ej. `BTC/USDT`), el cliente lo codifica con `encodeURIComponent` y la ruta usa el convertidor `{symbol:path}` (D119).

## 3. Decisiones

| # | Decisión | Motivo |
| :--- | :--- | :--- |
| D115 | **Fase 4 dividida en dos specs.** Esta cubre 4.1–4.5 más la infraestructura de Playwright; 4.6–4.9 y el E2E completo de 4.10 van en la siguiente. | Elegido por el usuario. Incrementos pequeños (misión §4.7): se entrega primero una UI de lectura verificable. |
| D116 | **Dependencias nuevas del frontend, aprobadas por el usuario el 2026-11-15:** `lightweight-charts`, `zustand`, `@tanstack/react-query`, `lucide-react` y la capa de shadcn/ui (`class-variance-authority`, `clsx`, `tailwind-merge`, `tw-animate-css` y los paquetes `@radix-ui/*` que necesiten los componentes copiados), más `@playwright/test` (dev). El CLI `shadcn` se ejecuta con `npx` y no queda como dependencia. **No** se añade MSW. La lista exacta de paquetes se fija en la tarea 1.1 y se registra en el changelog de `tech-stack.md`; cualquier paquete fuera de esta lista exige nueva aprobación. | `tech-stack.md` §2 ya decide estas librerías. El usuario descartó MSW. Regla del proyecto: ninguna dependencia sin aprobación. |
| D117 | **Sin dependencias nuevas en el backend.** CORS con `starlette.middleware.cors.CORSMiddleware` (incluido en FastAPI); el WebSocket usa el soporte nativo de FastAPI/Starlette. | Menos superficie; nada que aprobar. |
| D118 | **Cajas FVG desde un endpoint determinista**, no desde el LLM: `GET /market/structure` ejecuta `analyze_structure` (Fase 2) sobre las velas de la BD. Las zonas de entrada/SL/TP salen de `TradeSignalSchema` de `GET /signals/active`. La UI nunca recalcula estructura ni riesgo. | `TradeSignalSchema` no contiene FVG, y los FVG deben ser reproducibles y auditables (principio 2). |
| D119 | **El navegador llama directo al backend** (`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`) con **CORS** en FastAPI (`CORS_ALLOW_ORIGINS`, por defecto `http://localhost:3000`), en lugar de un proxy `rewrites` de Next. | Un proxy de Next puede almacenar en búfer el SSE y no es una vía fiable para WebSocket; en local y con un único usuario CORS es más simple y robusto. Las variables `NEXT_PUBLIC_` se incrustan en el *build* (guía de variables de entorno de Next). |
| D120 | **Fuente de ticks = último cierre ingerido.** El WebSocket sondea la BD cada `WS_POLL_INTERVAL_S` (2 s) y emite `TickUpdateEvent` con el `close` de la vela más reciente del timeframe pedido, con `provisional = true`; los adaptadores solo devuelven velas cerradas (D5) y no hay feed en vivo. La UI muestra el aviso «Precio = último cierre ingerido (no es tiempo real)». La fuente es un `Protocol` (`TickSource`) para sustituirla por un feed real (p. ej. `watch_ticker` de ccxt) sin tocar el endpoint. | Elegido por el usuario («Fuente de ticks»). Honestidad sobre lo que es el dato; sin red en CI. |
| D121 | **Tipos de los eventos WebSocket generados.** OpenAPI no describe WebSockets: los esquemas `StreamEventEnvelope` y sus variantes se publican en `components` mediante una respuesta documental (mecanismo concreto fijado en la tarea 5.4 y registrado como decisión de implementación). El frontend usa los tipos generados; no se escribe ningún tipo de API a mano. El *envoltorio* del SSE (`AnalysisEventEnvelope`) ya existe (D108). | Principio 1 (esquemas primero, tipos generados). |
| D122 | **SSE de análisis con `fetch` + `ReadableStream`.** `EventSource` no admite `POST`, así que un analizador propio (`parseSseStream`) lee `data: <json>\n\n`, valida el discriminante `event` en la frontera (sin librería de validación nueva) y entrega eventos tipados con `AnalysisEventEnvelope`. Cancelar el análisis aborta el `fetch` (`AbortController`), lo que cancela el análisis en el backend (D87). Un reductor puro (`reduceAnalysisEvent`) construye el estado del feed. | `POST` con cuerpo JSON; lógica pura y testeable. |
| D123 | **Estrategia de datos en el cliente.** TanStack Query para REST (`ohlcv`, `instruments`, `structure`, `signals/active`; `staleTime` corto y `refetchInterval` solo para señales activas); Zustand solo para estado de UI (`symbol`, `timeframe`, panel abierto). Páginas y *layouts* son Server Components con el shell estático; los componentes con interactividad (gráfico, selector, feed) son `"use client"`. Con `cacheComponents` activo (`next.config.ts`), **no** se hace `fetch` de datos de mercado en servidor: todo ocurre en cliente tras la hidratación, con *skeleton*/estado de carga propio. Con `Activity` (navegación que conserva el estado), los efectos se limpian al ocultar la ruta: el hook del WebSocket cierra y reabre la conexión. | Guías de Next 16 (`cacheComponents`, TanStack Query, preservar estado de UI). Evita errores de datos no cacheados en el *build*. |
| D124 | **Playwright con red simulada en el navegador.** Los E2E de esta spec usan `page.route` (REST y SSE) y `page.routeWebSocket` para que no necesiten backend, BD ni LLM y sean deterministas; el servidor de la app es `next build && next start`. El flujo cubierto: abrir `/desk` → velas y overlays → cambiar símbolo/timeframe → lanzar análisis y ver el feed → alerta de señal por WebSocket. **No** cubre «ejecutar en paper → blotter» (depende de 4.6/4.7): 4.10 se cierra en la spec siguiente. Playwright se instala con `npx playwright install chromium` (descarga de navegador solo en local y en el job E2E de CI). | Elegido por el usuario (Playwright en esta spec). Sin red a proveedores en la CI. |
| D125 | **Precisión de precios en la UI.** Los precios llegan como cadena `Decimal`. Solo se convierten a `number` en **un único punto** (`lib/chart-data.ts`, necesario para `lightweight-charts`) y para mostrarlos se formatean con los decimales del `tick_size` del instrumento. La UI no hace aritmética de riesgo, tamaño ni PnL. | Principio 2; el número se usa solo para dibujar. |
| D126 | **Rutas y páginas marcadoras.** `/` redirige a `/desk`. `/desk` (gráfico + feed lateral), `/agents` (feed a pantalla completa con el formulario de análisis) y las páginas marcadoras `/backtest` y `/journal` con un texto fijo «Pendiente: paso 4.8» / «4.9». Interfaz solo en español, solo tema oscuro (sin conmutador). | Roadmap 4.1; no se esconde lo que falta. |
| D127 | **Errores visibles y honestos en la UI.** Los `detail` de la API (404, 422, 503) se muestran tal cual; los eventos `step_failed`/`analysis_failed` se muestran con el paso y el mensaje; un corte de red o de WebSocket se indica con estado «Reconectando…» (backoff exponencial con tope) y nunca se oculta. Sin `ANTHROPIC_API_KEY`/`GEMINI_API_KEY`, el 503 se muestra con su mensaje y el formulario permanece usable. | Tono de la misión: los errores nombran el dato problemático y no esconden fallos. |
| D128 | **Texto del modelo marcado.** El feed muestra `reasoning`/`rationale` con la etiqueta «Texto del modelo, no verificado» (D112 de la fase anterior) y separa visualmente los **hechos del código** (niveles, R:R, tamaño, motivos de veto) del texto libre del LLM. | Auditabilidad (principio 5) y honestidad. |
| D129 | **`lightweight-charts` 5.3.0.** Las series se crean con `addSeries(CandlestickSeries)`; los overlays de entrada/SL/TP y las cajas FVG se dibujan con `createPriceLine` sobre la serie (API estable de la v5), no con primitivas. La geometría y los colores viven en `lib/overlays.ts` y se prueban sin canvas; el E2E comprueba que los overlays existen y que los interruptores los ocultan. | La API de primitivas de la v5 no cubría las líneas de precio con etiqueta; `createPriceLine` es suficiente y verificable. |
| D130 | **OpenAPI de los eventos WebSocket.** Se publica `StreamEventEnvelope` en `components/schemas` con un endpoint documental: `GET /api/v1/ws/stream/_openapi_docs`, `response_model=StreamEventEnvelope` y una descripción que aclara que no es un endpoint real. El WebSocket envía un evento JSON plano por mensaje. Un test comprueba que `openapi.json` contiene el componente y `npm run gen:api` genera sus tipos. | OpenAPI no describe WebSockets; el endpoint documental mantiene el principio de tipos generados (D121). |
| D131 | **Componentes shadcn/ui añadidos.** `button`, `badge`, `select`, `tabs`, `scroll-area`, `separator`, `skeleton` y `tooltip`; sus dependencias `@radix-ui/*` son `react-slot`, `react-select`, `react-tabs`, `react-scroll-area`, `react-separator` y `react-tooltip`. No se copiaron más componentes ni se instalaron paquetes fuera de D116. | Lista mínima necesaria para el shell, los selectores, el feed y el gráfico. |

## 4. Variables de entorno nuevas

**Backend** (`backend/.env.example`, todas opcionales):

```dotenv
CORS_ALLOW_ORIGINS=http://localhost:3000   # orígenes separados por comas
WS_POLL_INTERVAL_S=2.0                     # sondeo del WebSocket (0.5-60 s)
```

**Frontend** (`frontend/.env.example`; `frontend/.env.local` fuera de git; se incrustan en el *build*):

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8000   # base del backend (REST y SSE)
NEXT_PUBLIC_WS_URL=ws://localhost:8000      # base del WebSocket
```

Ninguna es un secreto. `Settings` valida `WS_POLL_INTERVAL_S` y que `CORS_ALLOW_ORIGINS` no contenga `*` junto con credenciales.

## 5. Contexto, tono y patrones a seguir

- **Next.js 16 no es el que conoces** ([`frontend/AGENTS.md`](../../frontend/AGENTS.md)): antes de cada tarea de UI se lee la guía relevante en `frontend/node_modules/next/dist/docs/01-app/` (en particular `01-getting-started/05-server-and-client-components.md`, `06-fetching-data.md`, `02-guides/client-side-data-fetching/tanstack-query.md`, `02-guides/environment-variables.md`, `02-guides/lazy-loading.md`, `02-guides/preserving-ui-state.md` y `02-guides/testing/playwright.md`). La configuración actual ([`next.config.ts`](../../frontend/next.config.ts)) activa `cacheComponents` y `partialPrefetching`.
- **Texto de la UI:** español técnico, denso, sin lenguaje promocional ni promesas de rentabilidad; números con el formato del instrumento; etiquetas claras de dato provisional.
- **Esquemas primero:** el grupo 2 escribe `stream.py` y sus tests antes de endpoints; el grupo 6 regenera tipos; la UI (grupo 7) solo consume tipos generados de [`frontend/types/api.ts`](../../frontend/types/api.ts) (`npm run gen:api`).
- **Patrones existentes del backend:** router en [`app/api/v1/router.py`](../../backend/app/api/v1/router.py); endpoint de referencia [`app/api/v1/market.py`](../../backend/app/api/v1/market.py); repositorios [`app/repositories/ohlcv.py`](../../backend/app/repositories/ohlcv.py), [`instruments.py`](../../backend/app/repositories/instruments.py) y [`trade_signals.py`](../../backend/app/repositories/trade_signals.py); estructura con [`app/quant/structure.py`](../../backend/app/quant/structure.py) (`analyze_structure`); patrón SSE/envoltorio de [`app/api/v1/agents.py`](../../backend/app/api/v1/agents.py); tests `db` con `@pytest.mark.db` y [`tests/conftest.py`](../../backend/tests/conftest.py); `get_settings()` de [`app/core/config.py`](../../backend/app/core/config.py).
- **Patrones existentes del frontend:** Vitest + Testing Library ([`vitest.config.mts`](../../frontend/vitest.config.mts), [`app/page.test.tsx`](../../frontend/app/page.test.tsx)); alias `@/`; excluye `e2e/` de Vitest (ya previsto); TypeScript estricto y **sin `any`**.
- **Tests de UI:** componentes y hooks con fetch simulado (`vi.fn`/`vi.stubGlobal`), WebSocket falso (clase simulada) y `lightweight-charts` simulado con `vi.mock` (jsdom no tiene canvas); la lógica de dibujo se aísla en funciones puras (`lib/chart-data.ts`, `lib/overlays.ts`, `lib/sse.ts`, `lib/analysis-reducer.ts`) que se prueban directamente. Ningún test llama a la red.
- **Backend:** tests del WebSocket con `starlette.testclient.TestClient.websocket_connect` y una `TickSource` falsa; sin red.
- **Fuente de verdad:** si esta spec contradice `tech-stack.md`, prevalece `tech-stack.md`; su changelog recoge las dependencias (D116) y variables nuevas.

## 6. Preguntas abiertas y riesgos

| Tema | Estado | Qué hacer |
| :--- | :--- | :--- |
| Versión de `lightweight-charts` | Cerrada: **5.3.0**. | Series con `addSeries(CandlestickSeries)` y overlays con `createPriceLine` (D129). |
| Cajas FVG y zonas | Resuelta: se dibujan con líneas de precio (`createPriceLine`), no con primitivas. | Geometría pura en `lib/overlays.ts` (probada) y E2E que comprueba presencia/visibilidad de overlays. |
| Ciclo de vida del gráfico | Resuelto: se crea en el ref callback y se destruye al desmontar. | El E2E comprueba que el canvas existe; un ciclo crear/destruir en bucle dejaba el gráfico vacío. |
| Ticks provisionales (D120) | Aceptado. | El precio solo se mueve cuando se ingiere una vela nueva (CLI); aviso visible. Feed real en una fase posterior. |
| WebSocket y navegación con `Activity` (D123) | Riesgo bajo/medio: conexiones duplicadas o colgadas al ocultar/mostrar rutas. | Limpieza en `useEffect`, reconexión con backoff y test de montaje/desmontaje. |
| CORS en local (D119) | Aceptado. | Origen configurable; el WebSocket valida el origen solo si se define la lista (sin credenciales). |
| SSE por `fetch` (D122) | Riesgo bajo: *buffering* intermedio. | Sin proxy; el test del analizador cubre fragmentos partidos y eventos incompletos. |
| Sin `ANTHROPIC_API_KEY` ni `GEMINI_API_KEY` (D127) | Aceptado: el análisis real no se puede probar de extremo a extremo todavía. | La UI muestra el 503; los E2E usan SSE simulado; el recorrido con modelo real es manual y opcional (como D92). |
| Playwright en CI (D124) | Implementado: job `e2e` con Chromium, caché de `~/.cache/ms-playwright` y subida del informe si falla. | Riesgo residual bajo: si el job se vuelve inestable, se mantiene como no bloqueante y se anota. |
| 4.10 no se cierra | Aceptado (D115). | El roadmap marca 4.1–4.5 `[x]`; 4.10 sigue `[ ]` con una nota: «E2E de lectura hecho en la Fase 4.1; falta el flujo con paper trading». |
| Esquemas de eventos en OpenAPI (D121) | Riesgo bajo: OpenAPI no describe WebSockets. | Respuesta documental + test de que `components` contiene `StreamEventEnvelope`; verificar que `gen:api` lo genera. |
| Rendimiento del gráfico | Riesgo bajo. | Tope de 5 000 velas en `ohlcv`; el gráfico carga 500 por defecto. |
