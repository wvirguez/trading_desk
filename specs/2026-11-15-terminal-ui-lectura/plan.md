# Plan — Fase 4 (parte 1): Terminal UI de lectura

Regla de cada grupo: **esquema → tests → implementación**, y termina en un commit verde (backend: `ruff`, `mypy`, `pytest`; frontend: `lint`, `typecheck`, `test`, `build`). Decisiones D115–D128 en [`requirements.md`](requirements.md). Los grupos se pueden implementar por separado, en este orden. Los comandos del backend se ejecutan en `backend/` y los del frontend en `frontend/`. Cada tarea lleva su casilla `[ ]`: se marca `[x]` al implementarla y comprobarla.

**Antes de cualquier tarea de UI (grupo 7)** hay que leer la guía relevante en `frontend/node_modules/next/dist/docs/01-app/` (véase `requirements.md` §5): Next 16 tiene cambios incompatibles y `cacheComponents` está activo.

## 1. Dependencias y configuración

- [x] 1.1. Backend, `Settings` (`app/core/config.py`): `cors_allow_origins` (lista, por defecto `["http://localhost:3000"]`, leída de `CORS_ALLOW_ORIGINS` separada por comas) y `ws_poll_interval_s` (`float`, 2.0, rango 0,5–60). Actualizar `backend/.env.example`.
- [x] 1.2. Tests en `tests/test_config.py`: valores por defecto; `CORS_ALLOW_ORIGINS="http://a,http://b"` da dos orígenes; rechazo de `*`, de una cadena vacía y de `WS_POLL_INTERVAL_S=0`/`100`.
- [x] 1.3. Frontend, dependencias **aprobadas** (D116): `npm install lightweight-charts zustand @tanstack/react-query lucide-react`, la capa de shadcn/ui (`class-variance-authority clsx tailwind-merge tw-animate-css` y los `@radix-ui/*` que pidan los componentes) y, en dev, `@playwright/test`. Fijar versiones y leer la documentación de la versión instalada de `lightweight-charts` (API de series y primitivas). Generar los componentes de `components/ui/` con `npx shadcn@latest` (solo los necesarios: `button`, `select`, `tabs`, `badge`, `scroll-area`, `separator`, `skeleton`, `tooltip`); no añadir paquetes fuera de la lista de D116 sin preguntar.
- [x] 1.4. `frontend/.env.example` con `NEXT_PUBLIC_API_URL` y `NEXT_PUBLIC_WS_URL`; `lib/env.ts` que los lee con valores por defecto de desarrollo y falla con un mensaje en español si la URL no es válida. Comprobar que `.env.local` está en `.gitignore`.
- [x] 1.5. Tests de `lib/env.ts` (por defecto, URL inválida, barra final normalizada). `npm run lint`, `typecheck`, `test` y `build` siguen verdes.
- [ ] 1.6. Commit: `Feat: dependencias y configuracion del terminal (fase 4)`.

## 2. Esquemas Pydantic

- [x] 2.1. `app/schemas/stream.py`: `TickUpdateEvent`, `SignalAlertEvent`, `StreamErrorEvent`, la unión discriminada `StreamEvent` (por `type`) y `StreamEventEnvelope` (`RootModel`). `frozen=True`, `extra="forbid"`.
- [x] 2.2. Tests en `tests/schemas/test_stream.py`: `price` y los niveles viajan como cadena en JSON; `provisional` es `bool`; `SignalAlertEvent` solo admite una señal `APPROVED`; discrimina por `type` (incluido tipo desconocido o ausente → error); inmutabilidad; ida y vuelta JSON del envoltorio; `extra="forbid"`.
- [x] 2.3. `mypy --strict` pasa. Commit: `Feat: esquemas de eventos de stream`.

## 3. Base de datos: repositorios (sin migraciones)

- [x] 3.1. Tests `db` (`tests/repositories/test_trade_signals_repo.py`, ampliado): `list_approved_since(session, symbol, since)` devuelve solo `APPROVED` del símbolo creadas **después** de `since`, ordenadas ascendente por `created_at`, y excluye filas anteriores a la Fase 3 (sin `analysis_id`).
- [x] 3.2. `app/repositories/trade_signals.py`: `list_approved_since`. `app/repositories/ohlcv.py`: comprobar que `fetch_latest(limit=1)` basta para el último cierre; si no, añadir `latest_candle(session, instrument_id, timeframe, symbol)` con test `db`.
- [ ] 3.3. Commit: `Feat: consultas de señales nuevas y ultima vela`.

## 4. Lógica de dominio y servicios de datos

- [x] 4.1. Tests en `tests/services/test_stream.py` (con un reloj y una `TickSource` falsos): `StreamPoller` emite un `TickUpdateEvent` al inicio y solo vuelve a emitir cuando cambian el precio o la vela (no duplica eventos idénticos); emite `SignalAlertEvent` solo para señales `APPROVED` **posteriores** al momento de conexión y una única vez cada una; un fallo de la fuente emite `StreamErrorEvent` con mensaje en español y el sondeo continúa; el precio nunca es `float`.
- [x] 4.2. `app/services/stream.py`: `TickSource` (`Protocol`), `DbTickSource` (último cierre ingerido, D120) y `StreamPoller` (generador asíncrono de `StreamEvent`; intervalo y reloj inyectables). Sin importar FastAPI.
- [x] 4.3. Tests `db` de `app/services/market.py` (`tests/services/test_market_service.py`): `get_instruments` devuelve los 4 instrumentos del seed; `get_structure` coincide **exactamente** con `analyze_structure` sobre las mismas velas; símbolo desconocido → `InstrumentNotFoundError`; menos de `2n + 1` velas → `InsufficientDataError` con cantidades.
- [x] 4.4. `app/services/market.py`: `list_instruments` y `get_structure` (reutilizan `candles_to_frame` y `analyze_structure`; errores de dominio de `services/backtest.py`).
- [ ] 4.5. Commit: `Feat: servicio de stream y de estructura de mercado`.

## 5. Servicios y endpoints FastAPI

- [x] 5.1. Tests de la API (`tests/api/test_market.py`, ampliado, `@pytest.mark.db`): `GET /market/instruments` → 200 con 4 instrumentos y `Decimal` como cadena; `GET /market/structure` → 200 con el esquema completo, 404 con símbolo desconocido, 422 con datos insuficientes (mensaje con cantidades), 422 con `n` fuera de 1–10.
- [x] 5.2. Tests del WebSocket (`tests/api/test_stream_ws.py`, con `TestClient.websocket_connect` y una `TickSource` sustituida por dependencia): el primer mensaje es un `TickUpdateEvent` válido; una señal nueva produce un `SignalAlertEvent`; símbolo desconocido (`BTC/XXX`) cierra con 1008 y motivo en español; `tf` inválido cierra con 1008; el símbolo con `/` funciona codificado; al cerrar el cliente el sondeo termina (sin tareas colgadas).
- [x] 5.3. Tests de CORS (`tests/api/test_cors.py`): un origen permitido recibe `access-control-allow-origin`; uno no permitido, no.
- [x] 5.4. `app/api/v1/market.py` (instrumentos y estructura), `app/api/v1/stream.py` (`WS /ws/stream/{symbol:path}`, dependencia `get_tick_source` sustituible) y `CORSMiddleware` en `app/main.py` con `Settings.cors_allow_origins`; registrar en `router.py`. Publicar `StreamEventEnvelope` en `components` de OpenAPI mediante una respuesta documental (D121), registrar el mecanismo elegido como decisión de implementación y añadir un test de que `openapi.json` lo contiene. Errores de dominio → `HTTPException` con `detail` en español.
- [ ] 5.5. Commit: `Feat: endpoints de instrumentos, estructura y WebSocket de stream`.

## 6. Tipos TS generados

- [x] 6.1. `uv run python scripts/export_openapi.py` → `backend/openapi.json` actualizado.
- [x] 6.2. En `frontend/`: `npm run gen:api` → `frontend/types/api.ts`. No se escribe ningún tipo de API a mano; comprobar `StreamEventEnvelope`, `TickUpdateEvent`, `SignalAlertEvent`, `MarketStructureResult` y la ruta de `instruments`/`structure`.
- [x] 6.3. `npm run typecheck` y `npm run build` pasan; sin diff al regenerar por segunda vez.
- [x] 6.4. Commit: `Ud: contrato OpenAPI y tipos TS de la fase 4`.

## 7. UI de Next.js

Cada subgrupo es un commit independiente. En todos: leer antes la guía de Next relevante; esquema/tipos generados → tests → implementación; Server Components por defecto y `"use client"` solo donde haga falta (D123); TypeScript estricto y **sin `any`**; texto solo en español; sin `fetch` de datos de mercado en servidor.

### 7A. Layout, navegación, store y providers (4.1)

- [x] 7A.1. Tests: `store/terminal.ts` (Zustand: valores por defecto `BTC/USDT`/`1h`, `setSymbol`, `setTimeframe`, no acepta un timeframe inválido); `lib/api.ts` (`apiGet` con la URL base, errores 4xx/5xx convertidos a un `ApiError` con el `detail` del backend y el estado HTTP; error de red con mensaje en español); `lib/format.ts` (decimales según `tick_size`, sin pasar por `float` para el texto).
- [x] 7A.2. Tests de componentes (Testing Library): `Sidebar` muestra los cuatro enlaces `/desk`, `/backtest`, `/agents`, `/journal` y marca el activo; `/backtest` y `/journal` muestran «Pendiente: paso 4.8» / «4.9».
- [x] 7A.3. Implementar: `app/layout.tsx` (`lang="es"`, tema oscuro fijo, metadata del terminal, fuentes existentes), `components/shell/{providers,sidebar,topbar}.tsx` (`QueryClientProvider` con cliente único en el navegador), `store/terminal.ts`, `lib/api.ts`, `lib/format.ts`; `app/page.tsx` redirige a `/desk`; páginas `app/desk`, `app/agents`, `app/backtest`, `app/journal` (las dos últimas marcadoras). Eliminar la plantilla de `create-next-app` y su test (`app/page.test.tsx`) sustituyéndolo por tests reales.
- [x] 7A.4. `lint`, `typecheck`, `test`, `build` en verde. Commit: `Feat: layout del terminal, store y providers`.

### 7B. Gráfico de velas (4.2)

- [x] 7B.1. Tests de lógica pura `lib/chart-data.ts` (único punto `Decimal → number`, D125): `candlesToSeries` convierte las velas ordenadas ascendente y en segundos UTC, descarta duplicados y avisa de huecos; `applyTick(series, tick)` actualiza la última vela (ajusta `high`/`low`/`close`) y abre una nueva solo si el `ts` es posterior.
- [x] 7B.2. Tests de hooks y componentes con `fetch` simulado y `lightweight-charts` simulado (`vi.mock`): `useInstruments` y `useOhlcv(symbol, tf)` (estados de carga, error 404/422/503 y éxito); `SymbolSelect` lista los símbolos del endpoint y cambia el store; `TimeframeSelect` ofrece `5m, 15m, 1h, 4h, 1d` y cambia el store; `CandleChart` crea el gráfico al montar, llama a `setData` con las velas, se limpia al desmontar y muestra un estado vacío en español («Sin velas para BTC/USDT 1h. Ingiere datos con la CLI.»).
- [x] 7B.3. Implementar `components/chart/{candle-chart,symbol-select,timeframe-select}.tsx` (`"use client"`; carga del gráfico con `next/dynamic` `ssr: false` dentro de un componente cliente), `hooks/{use-instruments,use-ohlcv}.ts`, `lib/chart-data.ts`; `app/desk/page.tsx` con barra superior (selectores) y el gráfico. Estados de carga con `skeleton`, errores visibles (D127).
- [ ] 7B.4. Verificar a mano con datos ingeridos que el gráfico muestra las velas y cambia con el selector. Commit: `Feat: grafico de velas con selector de simbolo y timeframe`.

### 7C. Overlays de señal y estructura (4.3)

- [x] 7C.1. Tests de `lib/overlays.ts` (puro): `signalToOverlay(signal)` devuelve entrada, SL y TP como niveles y una zona entre entrada y SL (largo/corto), con etiquetas «Entrada», «SL», «TP» y el R:R tal cual lo entrega el backend (la UI **no** recalcula R:R); `fvgToBox(fvg, series)` devuelve rectángulos con color según dirección y estilo atenuado si está mitigado; filtra por el símbolo y timeframe activos.
- [x] 7C.2. Tests de hooks/componentes: `useActiveSignals` (`GET /signals/active`, filtra por símbolo activo, `refetchInterval`) y `useStructure(symbol, tf)`; un componente `SignalList` muestra estado (`APPROVED`), dirección, niveles formateados con el `tick_size`, R:R, riesgo y la marca «Texto del modelo, no verificado» para `rationale` (D128); el gráfico recibe los overlays y los dibuja (con la API del gráfico simulada, se comprueba que se crean las líneas de precio y las primitivas).
- [x] 7C.3. Implementar `lib/overlays.ts`, `hooks/{use-signals,use-structure}.ts`, `components/chart/overlays.tsx` (líneas de precio y primitivas de `lightweight-charts`, según la API de la versión instalada) y `components/signals/signal-list.tsx`; integrarlos en `/desk` con un interruptor para mostrar/ocultar FVG y señales.
- [ ] 7C.4. Verificación manual con una señal real o sembrada: aparecen entrada/SL/TP y cajas FVG. Commit: `Feat: overlays de senal y cajas FVG`.

### 7D. WebSocket de precio y alertas (4.4)

- [x] 7D.1. Tests de `lib/ws.ts` y `hooks/use-stream.ts` con una clase `WebSocket` simulada: la URL codifica el símbolo con `encodeURIComponent` y lleva `tf`; un `TickUpdateEvent` actualiza la última vela (vía `applyTick`) y muestra el aviso «Precio = último cierre ingerido (no es tiempo real)»; un `SignalAlertEvent` invalida la consulta de señales activas y muestra un aviso; un mensaje que no es JSON válido o con `type` desconocido se ignora con un registro en consola, no rompe el hook; cierre inesperado → estado «Reconectando…» con backoff exponencial y tope, y sin reconectar tras desmontar; cambiar símbolo o timeframe cierra la conexión anterior y abre otra; el desmontaje cierra el socket (sin fugas).
- [x] 7D.2. Implementar `lib/ws.ts` (conexión con backoff), `hooks/use-stream.ts` (`"use client"`), el indicador de conexión en la barra superior («Conectado», «Reconectando…», «Desconectado») y la integración con `CandleChart`.
- [ ] 7D.3. Verificación manual contra el backend con una ingesta incremental: la última vela cambia y no hay conexiones duplicadas al navegar entre rutas. Commit: `Feat: hook de WebSocket con reconexion y alertas de senal`.

### 7E. Feed de razonamiento de agentes (4.5)

- [x] 7E.1. Tests de `lib/sse.ts`: `parseSseStream` produce un evento por `data:` aunque lleguen fragmentados (trozos partidos a mitad de línea o de UTF-8), ignora comentarios y líneas vacías, rechaza un evento sin el discriminante `event` o con uno desconocido con un error que lo nombra, y termina limpio al cerrar el *stream*; `lib/analysis-reducer.ts`: `reduceAnalysisEvent` construye el estado (pasos con estado `running/completed/failed`, orden por `seq`, uso por paso y total, avisos, `outcome`, informe final) para los seis eventos y descarta eventos con `seq` repetido o anterior.
- [x] 7E.2. Tests de `hooks/use-analysis.ts` (con `fetch` simulado que devuelve un `ReadableStream`): `start(request)` hace `POST /api/v1/agents/analyze` con el cuerpo `AnalyzeRequest` y entrega los eventos en orden; 404/422/503 antes del *stream* producen un error con el `detail` exacto del backend y el formulario sigue usable; `analysis_failed` durante el *stream* se muestra con el paso y el mensaje; `cancel()` aborta el `fetch` y deja el estado «Cancelado»; desmontar aborta la petición.
- [x] 7E.3. Tests de componentes: `AnalysisForm` (símbolo y timeframe desde el store, marcos por defecto, botón «Analizar» deshabilitado mientras corre y «Cancelar» visible); `AnalysisFeed` muestra cada paso (`STRUCTURE`, `QUANT`, `PROPOSAL`, `GUARDS`, `RISK_AUDIT`) con modelo, tokens, latencia y coste (`—` si es `null`), los **hechos del código** (niveles, R:R, tamaño, motivos de veto) separados de la prosa del modelo etiquetada «Texto del modelo, no verificado» (D128), y el resultado final (`SIGNAL_APPROVED`, `SIGNAL_REJECTED`, `NO_TRADE` con su motivo); la señal aprobada aparece en el gráfico de `/desk` tras invalidar `signals/active`.
- [x] 7E.4. Implementar `lib/sse.ts`, `lib/analysis-reducer.ts`, `hooks/use-analysis.ts`, `components/agents/{analysis-form,analysis-feed,step-card}.tsx`; `/agents` (feed a pantalla completa) y panel lateral en `/desk` que reutiliza los mismos componentes. Los tipos vienen de `AnalysisEventEnvelope`, `AnalyzeRequest` y `AgentReportSchema` generados.
- [ ] 7E.5. Verificación manual: sin clave de LLM se ve el 503 con su mensaje; con clave (opcional, D92) el feed se rellena paso a paso. Commit: `Feat: feed de razonamiento de agentes por SSE`.

### 7F. E2E con Playwright (infraestructura, D124)

- [x] 7F.1. `playwright.config.ts` (Chromium, `webServer: next build && next start` en un puerto fijo, trazas en el primer reintento, `testDir: e2e`), scripts `test:e2e` en `package.json`, `e2e/` ya excluida de Vitest; `.gitignore` con `playwright-report/` y `test-results/`.
- [x] 7F.2. Utilidades de `e2e/support/`: simulación de REST (`page.route` a `/api/v1/**` con datos fijos: instrumentos, velas, estructura, señales), de SSE (cuerpo `text/event-stream` con eventos grabados) y de WebSocket (`page.routeWebSocket`), con *fixtures* en JSON versionados.
- [x] 7F.3. Pruebas `e2e/desk.spec.ts`: abrir `/desk` muestra velas, selectores y los overlays de la señal aprobada y las cajas FVG; cambiar de símbolo y de timeframe recarga las velas; un `TickUpdateEvent` del WebSocket simulado cambia el precio mostrado y el aviso de dato provisional está visible; un `SignalAlertEvent` muestra la alerta; `e2e/agents.spec.ts`: lanzar un análisis con SSE simulado muestra los cinco pasos y el resultado, y un 503 simulado muestra su mensaje y deja el formulario usable; la navegación llega a `/backtest` y `/journal` y muestra «Pendiente».
- [x] 7F.4. `npx playwright install chromium` y `npm run test:e2e` en verde en local. **No** se escribe aquí el flujo de paper trading (4.10 sigue pendiente). Commit: `Feat: E2E con Playwright del terminal de lectura`.

## 8. CI, documentación y cierre del roadmap

- [x] 8.1. CI (`.github/workflows/ci.yml`): en el job `frontend`, `npm ci` ya instala las dependencias nuevas; añadir un job `e2e` (instala Chromium con `npx playwright install --with-deps chromium`, ejecuta `npm run test:e2e` y sube `playwright-report/` si falla; caché de `~/.cache/ms-playwright`). Comprobar que no hay claves de LLM en el entorno y que `gen:api` y `export_openapi.py` siguen comprobando el contrato.
- [x] 8.2. `specs/tech-stack.md`: changelog «2026-11-15 (Fase 4.1)» con las dependencias del frontend (versiones reales de `package-lock.json`), las cuatro variables nuevas, CORS directo en lugar de proxy (D119), ticks provisionales (D120), SSE por `fetch` (D122) y la decisión de Playwright con red simulada (D124). Si cambia algo de la pila, actualizar también las secciones afectadas.
- [x] 8.3. `README.md`: sección «Terminal (frontend)» con cómo arrancar (`npm run dev`, variables, CORS), las rutas, qué es provisional (ticks, `/backtest` y `/journal`) y cómo ejecutar `npm run test:e2e`.
- [x] 8.4. Registrar en `requirements.md` las decisiones de implementación (D129 en adelante: versión de `lightweight-charts`, mecanismo de OpenAPI para el WebSocket, componentes shadcn finalmente añadidos) y actualizar la tabla de riesgos.
- [x] 8.5. Smoke manual (véase `validation.md`), PR y CI en verde.
- [x] 8.6. Marcar **4.1–4.5** como `[x]` en `specs/roadmap.md` con una nota breve; **4.10** permanece `[ ]` con la nota «E2E de lectura hecho; falta el flujo con paper trading (4.6/4.7)». Esta tarea la hace el usuario o el flujo principal tras validar (`/spec-validation`). Commit: `Ud: actualizacion de roadmap.md`.
