# Requisitos — Proveedor provisional Yahoo Finance (yfinance)

- **Rama:** `feat-proveedor-yahoo`
- **Roadmap:** no añade pasos nuevos; sustituye de forma **provisional** el origen de datos del paso 1.7 (OANDA) hasta tener un proveedor fiable. Referencias: [`mission.md`](../mission.md), [`tech-stack.md`](../tech-stack.md), [`2026-11-12-datos-y-esquemas`](../2026-11-12-datos-y-esquemas/requirements.md) (D6, D12, D13, D17).

## 1. Contexto

No hay cuenta OANDA practice y la Fase 1 quedó validada solo con fixtures. Para llegar al MVP con datos reales de FX, metales e índices, se usa **Yahoo Finance vía `yfinance`** como proveedor **provisional**. Se cambiará por uno más fiable después. El adaptador queda aislado detrás de `MarketDataAdapter` (principio de la misión: esquemas y contratos primero), de modo que el cambio posterior sea una migración de datos más un adaptador.

## 2. Alcance

### Dentro

1. `Provider.YAHOO` en el enum y en el `CHECK` de `instruments`.
1. **`Timeframe.M5 = "5m"`** (marco de ejecución del usuario) en el enum, en el `CHECK` de `timeframe` de `ohlcv_bars` y `trade_signals`, y en los adaptadores de Yahoo, ccxt y OANDA. Se conservan `4h` y `1d` (D36).
2. Migración de datos `0005`: los 3 instrumentos antes en `OANDA` pasan a `YAHOO` con su ticker de Yahoo.
3. `YahooAdapter` (`app/market_data/yahoo.py`), registrado en `registry.py`.
4. Remuestreo de `4h` a partir de `1h`.
5. Horizontes de backfill reducidos y configurables, con aviso cuando el proveedor devuelve menos historia de la pedida.
6. Documentación honesta de las limitaciones (README, `tech-stack.md`).

### Fuera

- Eliminar `OandaAdapter`, `Provider.OANDA` y sus ajustes: se conservan para cuando haya cuenta (D29).
- Datos en tiempo real o ticks.
- El proveedor definitivo.

### Instrumentos tras la migración

| `symbol` | `provider` | `provider_symbol` (Yahoo) | Nota |
| :--- | :--- | :--- | :--- |
| `BTC/USDT` | `BINANCE` | `BTC/USDT` | Sin cambios. |
| `EUR/USD` | `YAHOO` | `EURUSD=X` | Volumen siempre 0 (según este documento; no verificado en la prueba real). |
| `XAU/USD` | `YAHOO` | `GC=F` | **Decidido 2026-11-13:** `GC=F` es el futuro continuo del oro (**futuro, no spot**: puede diferir del spot por base/roll). `XAUUSD=X` no devuelve datos en Yahoo (`YFPricesMissingError`). Volumen: el de un futuro real (no se ha verificado). |
| `NAS100` | `YAHOO` | `^NDX` | Índice cash. La prueba real del grupo 1 mostró volumen distinto de 0 (no se asume 0). Alternativa: `NQ=F`. |

`tick_size` y `lot_size` no cambian (siguen provisionales).

## 3. Decisiones

| # | Decisión | Motivo |
| :--- | :--- | :--- |
| D28 | Dependencia aprobada: **`yfinance`** (runtime). Arrastra pandas y numpy, que **solo se usan dentro de `yahoo.py`**; el resto del código no los importa. Override de mypy para `yfinance.*`. | Elegido por el usuario. Proveedor provisional. |
| D29 | **Se añade `YAHOO` y se conserva `OANDA`.** El cambio futuro es otra migración de datos. | Elegido por el usuario. |
| D30 | Horizontes por defecto en `Settings`: `5m` → 59 días, `15m` → 59 días, `1h` → 729 días, `4h` → 729 días, `1d` → 5 años. Aplican solo a instrumentos de Yahoo. Binance mantiene D17 y añade `5m` → 90 días. | Límites de Yahoo **verificados con llamada real el 2026-11-13**: `5m`/`15m` aceptan 59 días y rechazan 60 o más (0 filas); `1h` acepta 730 días (12317 filas en EURUSD=X) y rechaza 800; `1d` devuelve 5 años. Se mantiene 59/729 por margen. Si Yahoo devuelve menos de lo pedido, el servicio lo dice en la salida (no se esconde). |
| D31 | `4h` no existe en Yahoo: se construye agrupando velas de `1h` en bloques de 4 h alineados a 00/04/08/12/16/20 UTC (open = primera, high = máx., low = mín., close = última, volume = suma). Se emite el bloque con las velas de `1h` **presentes** (al menos 1; volume = suma de las presentes) siempre que esté cerrado (`ts + 4h <= now`); los bloques parciales se **avisan** (D49). | Reescrito el 2026-11-13 (antes: solo bloques completos). Con huecos reales (GC=F 20–24 UTC, reapertura del domingo) descartar bloques dejaba el 4h casi vacío. Mantiene los 4 timeframes del MVP; el coste es que un 4h parcial no es comparable con uno completo, y por eso se avisa. |
| D32 | Las velas diarias de Yahoo se normalizan a `00:00 UTC` (el `ts` de Yahoo llega con la zona del mercado). Si no se puede alinear sin ambigüedad, el adaptador falla con `MarketDataError` y no inventa datos. | D6 sigue vigente: apertura en UTC. |
| D33 | El volumen de `EURUSD=X` es 0 o inexistente (según lo previsto; sin verificar). `^NDX` sí trae volumen distinto de 0 en la prueba real del grupo 1. `GC=F` es un futuro (no spot) y trae su volumen propio. Se guarda lo que devuelva Yahoo (0 si no hay) y se documenta; los estudios que dependan de volumen deben tener esto en cuenta. | Honestidad sobre la calidad del dato (misión). |
| D34 | `yfinance` es síncrono: se llama con `asyncio.to_thread`. Los errores de red o de formato se traducen a `MarketDataError` en español. | Evita bloquear el bucle de eventos. |
| D36 | **Se añade `5m` y se conservan `4h` y `1d`.** Conjunto del MVP: `5m`, `15m`, `1h`, `4h`, `1d`. Operativa del usuario: `1h` = contexto, `15m` = zona y dirección, `5m` = ejecución. | Elegido por el usuario. Cambio aditivo: no se rompe nada existente. |
| D37 | Con 5m y 15m limitados a ~59 días en Yahoo, se acepta como limitación temporal. La historia propia crece porque la BD conserva lo ya guardado: se recomienda ejecutar la ingesta incremental con frecuencia. La CLI avisa de la historia recortada. | Elegido por el usuario. |
| D35 | Tests **sin red**: se prueba con un descargador inyectable (`Callable` que devuelve el DataFrame) y fixtures JSON/CSV grabados a mano. La CI no llama a Yahoo. | Coherente con D11. |
| D38 *(implementación)* | `default_since(tf, now, settings, provider)` usa los horizontes de Yahoo (`backfill_days_5m_yahoo`, `_15m_yahoo`, `_1h_yahoo`, `_4h_yahoo`; `1d` = `backfill_years_1d` × 365) cuando `provider` es `YAHOO`; sin proveedor o con otro, mantiene D17. `incremental` (sin datos) y el `backfill` de la CLI pasan el proveedor del instrumento. | El horizonte depende del proveedor, no solo del timeframe. |
| D39 *(implementación)* | El aviso de historia recortada viaja por un atributo, no por excepción ni log del adaptador: `YahooAdapter.history_notice` (`HistoryNotice` con `.message`) se reinicia en cada `fetch_ohlcv`. `base.py` define el Protocol `HistoryReporter` (`runtime_checkable`, propiedad `history_notice`); el servicio lo lee con `isinstance` (tipado, sin `getattr`/`Any`) y lo copia a `IngestResult.notice: str \| None`. La CLI emite un `warning` `historia_recortada` con el mensaje en español. `MarketDataAdapter` no cambia. | Los demás adaptadores no se tocan y la ingesta sigue devolviendo las velas disponibles. |
| D40 *(implementación)* | Los límites de historia de Yahoo viven como constantes `_MAX_HISTORY` en `yahoo.py` (5m/15m: 59 días; 1h/4h: 729) y **se duplican** con los `Settings` de D30. El adaptador recorta `start` a `now - límite` aunque el servicio pida más. | `yahoo.py` no depende de `Settings`; el recorte protege contra 0 filas por rechazo de Yahoo. Si cambia un límite hay que tocar ambos sitios. |
| D41 *(implementación)* | El aviso se emite solo si el recorte supera **1 hora** (`_NOTICE_TOLERANCE`). | El servicio calcula `start` unos instantes antes que el reloj del adaptador; sin tolerancia habría avisos falsos con el horizonte por defecto. |
| D42 *(implementación)* | El descargador es **síncrono** y se ejecuta con `asyncio.to_thread`. El real (`yahoo_downloader`) usa `Ticker.history(auto_adjust=False, actions=False, raise_errors=True)`. Cualquier excepción del descargador se traduce a `MarketDataError("Fallo al consultar Yahoo: <TipoDeExcepción>")`, sin volcar el mensaje original. | D34. |
| D43 *(implementación)* | Una respuesta **vacía** del descargador (`None` o 0 filas) **no es un error**: el adaptador devuelve `[]` y anota `empty_notice` (`EmptyResponseNotice`: «Yahoo no devolvió velas para <ticker> <tf> entre X e Y (mercado cerrado o sin datos nuevos…)»), que viaja por `notices` y la CLI emite como `aviso_ingesta`. La CLI dice «no se descargó ninguna vela» y el exit code es 0. Red, formato y columnas OHLCV ausentes **siguen** siendo `MarketDataError`. | Corregido tras revisión (antes: error). Un `incremental` en fin de semana o con el mercado cerrado recibe 0 filas de forma legítima y no debe romper un cron. Limitación asumida: Yahoo también responde 0 filas cuando bloquea o rechaza el rango y eso **no se distingue** de una respuesta legítima; por eso el aviso es visible. |
| D44 *(implementación)* | Velas diarias: se usa la **fecha local** del índice de Yahoo a las 00:00 y se emite `00:00 UTC` de esa fecha (D32). Si la hora local no es 00:00 o hay dos velas distintas para la misma fecha, `MarketDataError`. En intradía, los duplicados se resuelven con «gana el último»; las filas con algún precio NaN se omiten y el volumen NaN es 0. | Evita inventar alineaciones. |
| D45 *(implementación)* | `4h`: se pide `1h` con el rango ampliado a bloques completos de 4 h, se descartan las velas de `1h` aún abiertas **antes** de agrupar y se emiten los bloques cerrados con >= 1 vela de `1h` (D31, D49). | D31. |
| D46 *(implementación)* | `mypy`: override `ignore_missing_imports` para `yfinance.*` y `pandas.*` en `pyproject.toml`; el `Any` indispensable queda confinado a `yahoo.py` (valores de filas de pandas). `pandas`/`numpy` no se importan fuera de `yahoo.py` salvo en los tests de Yahoo. | D28. |
| D47 *(implementación)* | Tests: `ccxt` ya usaba `timeframe.value` (solo faltaba probarlo: test parametrizado con `5m`); OANDA ya traía `M5` desde el grupo 2. El test `db` de backfill de los 5 timeframes usa `YahooAdapter` con un descargador que sirve los fixtures por intervalo; como los fixtures cubren fechas distintas, cada timeframe usa su propio reloj. | D35. |

## 4. Variables de entorno

Nuevas, opcionales: `BACKFILL_DAYS_5M_YAHOO`, `BACKFILL_DAYS_5M`, `BACKFILL_DAYS_15M_YAHOO`, `BACKFILL_DAYS_1H_YAHOO`, `BACKFILL_DAYS_4H_YAHOO`. No hay credenciales.

## 5. Tono y patrones

- Mensajes en español, técnicos y honestos. Ejemplo: `"Yahoo devolvió 59 días de 15m; se pidieron 365"`.
- Mismo patrón que [`ccxt_adapter.py`](../../backend/app/market_data/ccxt_adapter.py): adaptador de un solo uso, reloj inyectado, `drop_open_candle`.
- `mypy --strict`: pandas queda confinado a `yahoo.py`, sin `Any` repartido.

## 6. Riesgos

| Tema | Estado | Qué hacer |
| :--- | :--- | :--- |
| `yfinance` es **no oficial** y puede romperse o ser bloqueado por Yahoo | Alto | Aislado tras `MarketDataAdapter`; sustitución planificada. |
| Términos de uso de Yahoo ambiguos | Medio | Solo uso personal; anotado en `tech-stack.md`. |
| Ticker `XAUUSD=X` sin datos (verificado 2026-11-13) | Resuelto | Se usa `GC=F` en la migración `0005` (futuro, no spot; precio puede diferir del spot). |
| 5m y 15m con solo ~59 días de historia: pocos datos para backtests de ejecución | Alto | Aceptado (D37); es la razón principal para cambiar de proveedor antes de la Fase 2 seria. |
| Los límites de historia y de intervalos son de memoria | Medio | Comprobarlos en el primer grupo y ajustar D30 antes de seguir. |
| Datos de Yahoo ≠ datos de un broker (OTC) | Aceptado | Provisional; los backtests no son comparables con los de otro proveedor. |
| D48 *(implementación)* | **NAS100 (`^NDX`) no admite `1h` ni `4h` con Yahoo.** Comprobado con datos reales el 2026-11-13: Yahoo entrega las velas de 1h de `^NDX` abriendo a **:30 UTC** (14:30–20:30) y `CandleSchema` exige alineación a la hora, así que el backfill fallaba entero. El adaptador rechaza la combinación **antes** de llamar al descargador con `UnsupportedTimeframeError(MarketDataError)` (tabla `_UNSUPPORTED` por ticker en `yahoo.py`). La CLI `--all` la **omite** con aviso (`ingesta_omitida`, «omitido: ...»), sin contarla como fallo ni dar exit 1 (el resumen la cuenta aparte); pedida explícitamente (`--symbol NAS100 --tf 1h`) es error con exit 1. NAS100 queda en 5m, 15m y 1d. | Elegido por el usuario: no re-alinear ni inventar datos. |
| D49 *(implementación)* | Aviso de bloques 4h parciales: el adaptador anota `partial_notice` (`PartialBlocksNotice(partial, total)`, «4h: N de M bloques se construyeron con menos de 4 velas de 1h.») junto a `history_notice` (D30). La propiedad `notices` los junta; el protocolo `HistoryReporter` pasó a `NoticeReporter` y `IngestResult.notice: str | None` a `notices: list[str]`, de modo que ambos avisos coexisten. La CLI emite un `aviso_ingesta` por cada uno (antes `historia_recortada`). Solo cuentan los bloques emitidos (cerrados). | D31. |
| D50 *(implementación)* | `--all` sin `--tf` recorre, por instrumento, solo los timeframes con horizonte configurado para su proveedor (`ingestion.DEFAULT_TIMEFRAMES`): BINANCE y YAHOO → `5m`, `15m`, `1h`, `4h`, `1d` (NAS100 omite `1h`/`4h`, D48); OANDA → `15m`, `1h`, `4h`, `1d`. El `5m` de OANDA no tiene horizonte propio (usaría el de Binance, 90 días), así que solo se descarga pidiéndolo con `--tf 5m`. Al inicio de `--all` la CLI imprime «Alcance: N combinaciones instrumento/timeframe». Además, el downgrade de `0005` descarta TODAS las velas de EUR/USD, XAU/USD y NAS100 (datos de Yahoo) para no mezclar fuentes al volver a OANDA. | Revisión: `backfill --all` descargaba 5m de OANDA sin planificar. Con los 4 instrumentos actuales (todos Binance/Yahoo) son 20 combinaciones, 2 omitidas. |
