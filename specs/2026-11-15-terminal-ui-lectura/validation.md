# Validación — Fase 4 (parte 1): Terminal UI de lectura

## 1. Automatizado (CI y PR)

- Backend (en `backend/`): `uv run ruff check`, `uv run ruff format --check`, `uv run mypy app`, `uv run pytest` (incluidos `@pytest.mark.db`, golden y propiedades, con la BD de test migrada a `head`: `DATABASE_URL="$TEST_DATABASE_URL" uv run alembic upgrade head`; esta fase no añade migraciones).
- Frontend (en `frontend/`): `npm run lint`, `npm run typecheck`, `npm test` y `npm run build`.
- E2E (en `frontend/`): `npm run test:e2e` (Playwright, Chromium, red simulada en el navegador, D124).
- `uv run python scripts/export_openapi.py` y `npm run gen:api` no dejan diff (`backend/openapi.json` y `frontend/types/api.ts` versionados y al día).
- **Ningún test llama a la red, a un proveedor de mercado ni a un LLM real**, y la CI no define `ANTHROPIC_API_KEY` ni `GEMINI_API_KEY`.
- TypeScript estricto: **cero `any`** en `frontend/` fuera de `types/api.ts` generado (se comprueba con `grep` y con ESLint).

### Afirmaciones concretas que deben existir en los tests

| Afirmación | Dónde |
| :--- | :--- |
| `Settings`: `CORS_ALLOW_ORIGINS` por defecto y separado por comas; rechaza `*` y vacío; `WS_POLL_INTERVAL_S` fuera de 0,5–60 se rechaza. | `backend/tests/test_config.py` |
| Los eventos de stream viajan con precios como cadena, discriminan por `type`, rechazan tipos desconocidos y campos extra; `SignalAlertEvent` solo admite `APPROVED`. | `backend/tests/schemas/test_stream.py` |
| `list_approved_since` solo devuelve señales `APPROVED` posteriores, ordenadas y con `analysis_id`. | `backend/tests/repositories/test_trade_signals_repo.py` |
| `StreamPoller` no duplica ticks idénticos, emite cada alerta una sola vez, solo para señales posteriores a la conexión, y un fallo de la fuente emite `StreamErrorEvent` en español sin detener el sondeo. | `backend/tests/services/test_stream.py` |
| `get_structure` coincide exactamente con `analyze_structure` sobre las mismas velas; símbolo desconocido y datos insuficientes lanzan sus errores con cantidades. | `backend/tests/services/test_market_service.py` |
| `GET /market/instruments`: 200 con los 4 instrumentos; `GET /market/structure`: 200, 404, 422 (datos insuficientes y `n` fuera de rango). | `backend/tests/api/test_market.py` |
| WebSocket: primer mensaje `TickUpdateEvent` válido; alerta de señal nueva; cierre 1008 con motivo en español para símbolo o `tf` inválidos; símbolo con `/` codificado; el sondeo termina al cerrar. | `backend/tests/api/test_stream_ws.py` |
| CORS: el origen permitido recibe la cabecera; el no permitido, no. | `backend/tests/api/test_cors.py` |
| `openapi.json` contiene `StreamEventEnvelope` y `MarketStructureResult`. | `backend/tests/api/test_stream_ws.py` |
| `lib/env.ts` normaliza la URL y falla con mensaje en español si es inválida. | `frontend/lib/env.test.ts` |
| El store Zustand tiene los valores por defecto `BTC/USDT`/`1h` y rechaza un timeframe inválido. | `frontend/store/terminal.test.ts` |
| `apiGet` convierte 4xx/5xx en `ApiError` con el `detail` del backend y los errores de red en un mensaje en español; `format` usa los decimales del `tick_size`. | `frontend/lib/api.test.ts`, `frontend/lib/format.test.ts` |
| La barra lateral enlaza `/desk`, `/backtest`, `/agents`, `/journal` y marca la activa; `/backtest` y `/journal` muestran «Pendiente». | `frontend/components/shell/sidebar.test.tsx`, `frontend/app/*/page.test.tsx` |
| `candlesToSeries` ordena, deduplica y usa segundos UTC; `applyTick` actualiza la última vela y abre una nueva solo con `ts` posterior; **la conversión `Decimal → number` solo ocurre en `lib/chart-data.ts`**. | `frontend/lib/chart-data.test.ts` |
| `CandleChart` crea el gráfico, carga datos, se limpia al desmontar y muestra el estado vacío en español; los selectores cambian el store. | `frontend/components/chart/*.test.tsx` |
| `signalToOverlay` usa el R:R del backend (no lo recalcula) y `fvgToBox` distingue dirección y mitigación; el gráfico dibuja líneas y primitivas (con la API simulada). | `frontend/lib/overlays.test.ts`, `frontend/components/chart/overlays.test.tsx` |
| `SignalList` muestra estado, niveles con `tick_size`, R:R y la etiqueta «Texto del modelo, no verificado». | `frontend/components/signals/signal-list.test.tsx` |
| El hook del WebSocket codifica el símbolo, actualiza la última vela, muestra el aviso de dato provisional, invalida señales ante una alerta, ignora mensajes inválidos, reconecta con *backoff* y **cierra el socket al desmontar o al cambiar símbolo/timeframe**. | `frontend/hooks/use-stream.test.tsx`, `frontend/lib/ws.test.ts` |
| `parseSseStream` maneja fragmentos partidos (incluido UTF-8), comentarios y eventos inválidos con un error que nombra el problema. | `frontend/lib/sse.test.ts` |
| `reduceAnalysisEvent` construye el estado con los seis eventos, ordena por `seq` y descarta repetidos. | `frontend/lib/analysis-reducer.test.ts` |
| `useAnalysis`: `POST` con el `AnalyzeRequest`; 404/422/503 muestran el `detail` exacto; `analysis_failed` muestra paso y mensaje; `cancel()` y el desmontaje abortan el `fetch`. | `frontend/hooks/use-analysis.test.tsx` |
| El feed muestra los cinco pasos con modelo, tokens, latencia y coste (`—` si `null`), separa hechos del código y texto del modelo, y muestra `SIGNAL_APPROVED`/`SIGNAL_REJECTED`/`NO_TRADE`. | `frontend/components/agents/analysis-feed.test.tsx` |
| E2E: `/desk` con velas, overlays y FVG; cambio de símbolo/timeframe; tick y alerta por WebSocket simulado; análisis con SSE simulado y 503 simulado; navegación a las páginas marcadoras. | `frontend/e2e/desk.spec.ts`, `frontend/e2e/agents.spec.ts` |

## 2. Manual (smoke local)

Requisitos: Postgres local en marcha con datos ingeridos (Fase 1) para `BTC/USDT` en `1h`, `4h` y `1d` (≥ 100 velas cada uno), backend arrancado (`uv run uvicorn app.main:app --reload` en `backend/`) y `frontend/.env.local` con las dos URL.

1. `curl -s localhost:8000/api/v1/market/instruments | jq 'length'` → `4`. `curl -s "localhost:8000/api/v1/market/structure?symbol=BTC/USDT&tf=1h" | jq '{swings: (.swings|length), events: (.events|length), fvgs: (.fvgs|length)}'` → conteos coherentes. `symbol=XYZ` → 404 «Instrumento desconocido: XYZ».
2. CORS: `curl -s -i -H 'Origin: http://localhost:3000' localhost:8000/api/v1/health | grep -i access-control-allow-origin` → presente; con `Origin: http://evil.example` → ausente.
3. WebSocket (con `websocat`, `wscat` o una consola de navegador): conectar a `ws://localhost:8000/api/v1/ws/stream/BTC%2FUSDT?tf=1h` → llega un `{"type":"tick",...,"provisional":true}`; con `tf=2h` o símbolo desconocido, cierre con motivo en español.
4. `npm run dev` en `frontend/` y abrir `http://localhost:3000`: redirige a `/desk`. La interfaz está en español, oscura y sin restos de la plantilla de Next.
5. `/desk`: se ven las velas de `BTC/USDT 1h`; cambiar al selector de símbolo y de timeframe recarga el gráfico; los selectores y la barra superior muestran el estado de conexión («Conectado»).
6. Ticks: ingerir una vela nueva (`uv run python -m app.cli.ingest ...`) → la última vela se actualiza en ≤ `WS_POLL_INTERVAL_S` y el aviso «Precio = último cierre ingerido (no es tiempo real)» está visible. Parar el backend → «Reconectando…»; reiniciarlo → vuelve a «Conectado» sin recargar la página.
7. Overlays: con una señal `APPROVED` en BD (de un análisis real o sembrada a mano) aparecen en `/desk` las líneas de entrada, SL y TP, la zona y las cajas FVG; el interruptor las oculta y muestra.
8. Navegación: ir a `/agents`, a `/backtest` y a `/journal` y volver a `/desk` conserva símbolo y timeframe, y el WebSocket no queda duplicado (una sola conexión en la pestaña de red).
9. Análisis **sin clave de LLM**: en `/agents`, «Analizar» muestra el 503 «El análisis con agentes no está configurado: falta …» y el formulario sigue usable.
10. **Opcional, con clave real (D92):** con `ANTHROPIC_API_KEY` (o `AGENT_PROVIDER=google` y `GEMINI_API_KEY`), «Analizar» rellena el feed paso a paso, con modelo, tokens y latencia por paso; la señal aprobada aparece en `/desk`; «Cancelar» a mitad detiene el análisis (comprobar en el backend que no quedan filas parciales). Anotar en la PR cualquier problema de prompts o de UX.
11. `npx playwright install chromium` y `npm run test:e2e` pasan en local.
12. `npm run gen:api` en `frontend/` y `git status`: sin cambios.

### Casos límite

- Símbolo sin velas (instrumento sin datos): el gráfico muestra «Sin velas para … Ingiere datos con la CLI.» y no se rompe; los overlays y el WebSocket no fallan.
- NAS100 con `1h`/`4h` (sin datos por Yahoo, D91): el selector permite el timeframe, el gráfico muestra el estado vacío y el análisis responde con el 422 del backend mostrado tal cual.
- Respuesta 5xx o red caída en cualquier consulta: mensaje visible con reintento manual; nunca una pantalla en blanco.
- SSE cortado a mitad (backend parado): el feed marca el análisis como interrumpido y muestra el error; no queda «en curso» para siempre.
- Dos análisis seguidos: el segundo reemplaza al primero en la vista y el primero se aborta; no se mezclan eventos de ambos.
- Cambiar de símbolo mientras llega un tick del anterior: el tick se descarta (no actualiza la vela del nuevo símbolo).
- Precios con muchos decimales (EUR/USD, `tick_size` 0.00001; BTC/USDT, `0.01`): el formato respeta los decimales del instrumento y no muestra notación científica.
- Ancho de ventana estrecho: el shell no genera desplazamiento horizontal de la página (el gráfico se redimensiona).

## 3. Tono

- Todo el texto visible está en **español**, técnico, denso y sin lenguaje promocional ni promesas de rentabilidad. Ejemplos: «Sin velas para BTC/USDT 1h. Ingiere datos con la CLI.», «Precio = último cierre ingerido (no es tiempo real)», «Reconectando…», «Texto del modelo, no verificado», «Pendiente: paso 4.8».
- Los errores nombran el dato problemático y se muestran tal cual los entrega la API (`detail`); no se suavizan ni se ocultan.
- Un dato provisional (ticks, proveedor Yahoo) se rotula como tal en la propia UI.
- No se expone ningún secreto: las claves de LLM solo viven en `backend/.env`; las variables `NEXT_PUBLIC_*` no contienen secretos.

## 4. Terminado cuando

- Todo lo automatizado está en verde en la PR y en `main`, incluidos los tests `db`, los E2E y el contrato sin diff.
- El smoke manual (pasos 1–9, 11 y 12) pasa. El paso 10 con clave real se ejecuta cuando haya clave; si no, queda anotado como pendiente en la PR y no bloquea el cierre (D92).
- **4.1–4.5** marcados `[x]` en `specs/roadmap.md` (tras `/spec-validation`); **4.10** permanece `[ ]` con su nota; `tech-stack.md` (changelog), el README y `requirements.md` (decisiones D129+) actualizados.
- Los tipos TS (incluidos `StreamEventEnvelope` y `MarketStructureResult`) están regenerados y sin diff.

**Se rechaza si:** la UI calcula riesgo, tamaño, R:R o PnL en lugar de mostrar lo que entrega el backend; hay un tipo de API escrito a mano o `any` fuera de `types/api.ts`; se añadió una dependencia fuera de la lista aprobada en D116; un test llama a la red, a un proveedor de mercado o a un LLM, o la CI necesita una clave; los precios pasan a `number` fuera de `lib/chart-data.ts` o se muestran con notación científica; un error de la API o del WebSocket se oculta o la UI queda en blanco; el WebSocket queda abierto tras desmontar o cambiar de símbolo; el texto del modelo se presenta sin la etiqueta «no verificado»; los ticks provisionales se presentan como tiempo real; el 4.10 se marca `[x]` sin el flujo de paper trading; o hay texto de interfaz en otro idioma que no sea español.
