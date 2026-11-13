# Requisitos — Fase 2: Motor cuantitativo y núcleo de riesgo determinista

- **Rama:** `phase-2-motor-cuantitativo-riesgo`
- **Roadmap:** pasos 2.1 – 2.10 de [`specs/roadmap.md`](../roadmap.md)
- **Referencias:** [`mission.md`](../mission.md), [`tech-stack.md`](../tech-stack.md), spec anterior [`2026-11-12-datos-y-esquemas`](../2026-11-12-datos-y-esquemas/requirements.md) y [`2026-11-13-proveedor-yahoo`](../2026-11-13-proveedor-yahoo/requirements.md) (las decisiones continúan en **D51**).

## 1. Contexto

La Fase 1 dejó velas OHLCV normalizadas (`Decimal`, UTC, solo cerradas) en `ohlcv_bars` para los 4 instrumentos y `GET /market/ohlcv`. Los agentes de la Fase 3 no pueden existir sin las herramientas deterministas que van a invocar: features, estadísticos de régimen, estructura de mercado, tamaño de posición, Kelly, guardas de cartera y un backtester que valide hipótesis.

Esta fase construye el **motor cuantitativo (`app/quant/`)** y el **núcleo de riesgo (`app/risk/`)** como código puro, determinista y testeado, y expone `POST /api/v1/quant/backtest`. Cumple los principios de la misión: **2** (el LLM nunca calcula riesgo), **3** (veto determinista), **4** (circuit breakers 1 % por operación y 3 % de pérdida diaria) y **6** (reproducibilidad: mismos datos y configuración → mismas métricas, verificado con tests *golden*), y el criterio de éxito *«Backtest determinista con métricas reproducibles en los tests»*.

## 2. Alcance

### Dentro del alcance

1. **2.1 Features:** rendimientos logarítmicos, volatilidad móvil y ATR (Wilder) con polars.
2. **2.2 Estadísticos de régimen:** Z-score, exponente de Hurst y test ADF.
3. **2.3 Estructura de mercado:** swings, BOS, CHoCH y FVG, sin sesgo de anticipación.
4. **2.4 Clasificador de régimen:** `MEAN_REVERTING`, `TRENDING`, `HIGH_VOLATILITY_NOISE`.
5. **2.5 Position sizing** con `Decimal`, respetando tick size y lot size; nunca supera el riesgo máximo.
6. **2.6 Kelly fraccional y riesgo de ruina:** fórmulas puras con límites.
7. **2.7 Guardas de cartera:** pérdida diaria 3 %, exposición abierta, correlación (ventana fija) y veto por R:R < 1,8.
8. **2.8 Backtester vectorizado:** `BacktestConfig` → `BacktestMetricsSchema`, con **una sola estrategia de referencia fija** (reversión a la media por z-score).
9. **2.9 Tests *golden*** de determinismo sobre datasets fijos versionados.
10. **2.10 `POST /api/v1/quant/backtest`** y tabla `strategies` (parámetros y métricas en JSONB). Los datos se leen de `ohlcv_bars`.

### Fuera del alcance

- Agentes, herramientas PydanticAI y señales de agentes: Fase 3. Aquí solo se dejan las funciones puras que usarán.
- UI de backtest (paso 4.8): solo se generan los tipos TS.
- Costes de transacción y *slippage* en el backtester (véase la sección 6).
- Backtest de múltiples activos o de cartera; optimización de parámetros; *walk-forward*.
- Stops y take-profit dentro del backtest (la estrategia de referencia sale por señal, D56).
- Conversión de divisas del riesgo: los 4 instrumentos cotizan en USD/USDT y la cuenta se asume en USD (D60).
- Carga del estado de cartera (posiciones abiertas, PnL del día) desde la BD: llega con el paper trading (4.6). Las guardas reciben el estado como argumento.

### Esquemas Pydantic

Todos inmutables (`frozen=True`). Dinero en `Decimal`; ratios y estadísticos en `float` (D52).

**`app/schemas/enums.py`** (añadidos): `RegimeLabel` (`MEAN_REVERTING`, `TRENDING`, `HIGH_VOLATILITY_NOISE`), `StructureEventType` (`BOS`, `CHOCH`), `SwingKind` (`HIGH`, `LOW`), `VetoReason` (`RR_BELOW_MIN`, `RISK_PER_TRADE_EXCEEDED`, `DAILY_LOSS_LIMIT`, `OPEN_RISK_LIMIT`, `CORRELATED_RISK_LIMIT`, `SIZE_BELOW_LOT`, `INVALID_LEVELS`).

**`app/schemas/quant.py`**:

| Esquema | Campos |
| :--- | :--- |
| `SwingPoint` | `ts`, `kind: SwingKind`, `price: Decimal`, `confirmed_at: datetime` (vela en que se confirma, D55) |
| `StructureEvent` | `ts` (vela que rompe), `type: StructureEventType`, `direction: Direction` (sentido de la ruptura), `broken_swing_ts`, `level: Decimal` |
| `FairValueGap` | `ts` (vela central), `direction: Direction`, `low: Decimal`, `high: Decimal`, `mitigated_at: datetime \| None` |
| `MarketStructureResult` | `swings`, `events`, `fvgs` (listas ordenadas por `ts`) |
| `RegimeStats` | `hurst: float`, `adf_pvalue: float`, `zscore: float`, `volatility_ratio: float`, `n_obs: int` |
| `RegimeThresholds` | `hurst_mean_reverting=0.45`, `hurst_trending=0.55`, `adf_alpha=0.05`, `vol_ratio_high=1.5`, `min_obs=100` |
| `RegimeReport` | `label: RegimeLabel`, `stats: RegimeStats`, `thresholds: RegimeThresholds` |
| `BacktestConfig` | `symbol`, `timeframe`, `start: datetime \| None`, `end: datetime \| None`, `initial_capital: Decimal = 10000` (`> 0`), `zscore_window: int = 50` (10–500), `entry_z: float = 2.0` (`> 0`), `exit_z: float = 0.0` (`≥ 0`, `< entry_z`), `allow_short: bool = True` |
| `EquityPoint` | `ts`, `equity: Decimal` |
| `BacktestMetricsSchema` | `strategy_id: UUID`, `config: BacktestConfig`, `n_bars`, `n_trades`, `total_return`, `sharpe`, `max_drawdown`, `win_rate`, `expectancy`, `final_equity: Decimal`, `equity_curve: list[EquityPoint]`, `warnings: list[str]` |

**`app/schemas/risk.py`**:

| Esquema | Campos |
| :--- | :--- |
| `PositionSizeResult` | `units: Decimal`, `risk_amount: Decimal` (riesgo real), `risk_pct: Decimal` (real, ≤ pedido), `stop_distance: Decimal`, `notional: Decimal` |
| `KellyResult` | `full_kelly: float`, `fraction: float` (aplicada), `capped: bool` |
| `OpenPosition` | `symbol`, `direction`, `risk_amount: Decimal` |
| `PortfolioState` | `equity: Decimal`, `day_start_equity: Decimal`, `realized_pnl_today: Decimal`, `open_positions: list[OpenPosition]` |
| `ProposedTrade` | `symbol`, `direction`, `entry`, `stop_loss`, `take_profit: Decimal` |
| `GuardDecision` | `approved: bool`, `reasons: list[VetoReason]`, `messages: list[str]` (español, con el dato que incumple), `rr: Decimal \| None`, `size: PositionSizeResult \| None` |

### Tablas

| Tabla | Columnas | Notas |
| :--- | :--- | :--- |
| `strategies` | `id UUID` (`uuid_generate_v4()`), `name TEXT` (`zscore_mean_reversion`), `instrument_id SMALLINT` FK, `timeframe TEXT` (`CHECK`), `params JSONB` (el `BacktestConfig`), `metrics JSONB` (el resultado, sin la curva de capital), `config_hash TEXT` (SHA-256 de `params` canónico + rango de datos), `data_from`, `data_to TIMESTAMPTZ`, `created_at` | Una fila por backtest ejecutado (D63). Índice `(instrument_id, created_at DESC)`. |

### Endpoint

`POST /api/v1/quant/backtest` — cuerpo `BacktestConfig`, respuesta **200** `BacktestMetricsSchema`.

- `symbol` desconocido → **404** (`"Instrumento desconocido: XYZ"`).
- Parámetros inválidos (p. ej. `exit_z ≥ entry_z`) → **422** (validación Pydantic).
- Menos de `zscore_window + 2` velas, o más de `BACKTEST_MAX_BARS` → **422** con `detail` que dice cuántas hay y cuántas hacen falta (D69).
- Se persiste una fila en `strategies` por llamada correcta.

## 3. Decisiones

| # | Decisión | Motivo |
| :--- | :--- | :--- |
| D51 | **Una sola spec para la Fase 2 completa** (2.1–2.10), con grupos de plan que terminan en un commit verde. | Elegido por el usuario. |
| D52 | **Dinero en `Decimal`; series en `float64`.** Sizing, riesgo, límites, capital y `PositionSizeResult` usan `Decimal`; features, estadísticos y el backtester usan `float64` (polars/numpy). La conversión `Decimal → float` se hace en **un único punto** (`app/quant/data.py`, `candles_to_frame`), y los importes vuelven a `Decimal` con `Decimal(str(round(x, 10)))` en la frontera del esquema. | Elegido por el usuario. Aritmética exacta de ticks/lotes donde un redondeo puede violar un límite; velocidad y vectorización donde no. |
| D53 | **ADF con `statsmodels.tsa.stattools.adfuller`** (sobre `numpy`, `regression="c"`, `autolag="AIC"`); **Hurst implementado a mano** con numpy: pendiente de la regresión log-log de `std(x[t+τ] − x[t])` frente a `τ`, para `τ` de 2 a 20 (estimador de varianza de incrementos). R/S queda descartado por su sesgo en muestras cortas. Devuelve `nan` si hay menos de `min_obs` datos o la serie es constante. | Elegido por el usuario. Una función de ~15 líneas es más fácil de auditar y testear que otra dependencia. |
| D54 | **Dependencias nuevas** (ya decididas en `tech-stack.md` §5): `polars`, `numpy` (pasa de transitiva a explícita), `statsmodels` (arrastra `scipy` y `pandas` como transitivas) y, en dev, `hypothesis`. **Aprobadas por el usuario el 2026-11-13** (tarea 1.1). `pandas`/`scipy` no se importan en el código propio. | Regla del proyecto: ninguna dependencia nueva sin preguntar. |
| D55 | **Sin sesgo de anticipación (*look-ahead*).** Un swing de ventana `n` (por defecto 3 velas a cada lado) solo se *confirma* `n` velas después; `SwingPoint.confirmed_at` lo registra, y BOS/CHoCH/FVG solo pueden referirse a swings ya confirmados en la vela que rompe. Los features en `t` usan solo datos `≤ t`. | Sin esto, el backtest y los agentes verían el futuro y las métricas no valdrían nada. Se testea con *truncado*: calcular sobre `df[:k]` da lo mismo que las primeras `k` filas de calcular sobre `df`. |
| D56 | **Estrategia de backtest de referencia, simple y fija:** reversión a la media por z-score del precio de cierre (ventana `zscore_window`). Entra largo si `z ≤ −entry_z` y corto si `z ≥ +entry_z` (si `allow_short`); sale cuando `z` cruza `±exit_z` hacia el centro. Exposición fija de **1× el capital** (sin *sizing*, sin apalancamiento), sin stops. | Elegido por el usuario. Es solo un *arnés de validación* del motor; las señales de los agentes (Fase 3) usarán el sizing de 2.5. |
| D57 | **Ejecución sin anticipación:** la posición decidida con el cierre de la vela `t` se aplica al rendimiento logarítmico de `t → t+1` (`position.shift(1)`). El estado (entrar/mantener/salir) se calcula con marcas de entrada/salida y `forward_fill` de polars, sin bucles por vela. | Estándar anti-*look-ahead*; mantiene el backtester vectorizado como pide `tech-stack.md`. |
| D58 | **Métricas del backtest:** `total_return = equity_final/equity_inicial − 1`; `sharpe` anualizado = `media(r)/std(r, ddof=1) · √P` con `rf = 0`, y `0.0` si `std = 0`; `max_drawdown` = máxima caída pico-valle de la curva de capital (valor `≤ 0`); `win_rate` = operaciones ganadoras / operaciones; `expectancy` = media del rendimiento por operación (fracción del capital). `P` (periodos por año) sale de `periods_per_year(timeframe, session)`: cripto 365 días, el resto 252 días × velas por día. Una **operación** es un tramo continuo con la misma posición `≠ 0`. | Definiciones explícitas para que los tests golden fijen números exactos. |
| D59 | **Reproducibilidad numérica:** los `float` del resultado se redondean a **10 decimales** en la frontera del esquema; el `config_hash` y el orden de las velas (`ts` ascendente) son deterministas. Los tests golden comparan con igualdad exacta sobre esos valores redondeados. | Principio 6. Evita falsos fallos por ruido de 1e-16 entre versiones de librerías, sin perder rigor. |
| D60 | **Position sizing en `Decimal`:** `risk_amount = equity · risk_pct`; `distancia = |entry − stop|`, redondeada **hacia arriba** al múltiplo de `tick_size`; `units = risk_amount / distancia`, redondeado **hacia abajo** al múltiplo de `lot_size`. Si `units < lot_size` → `units = 0` con veto `SIZE_BELOW_LOT`. El riesgo real (`units · distancia`) nunca supera `risk_pct` (propiedad con hypothesis). Se asume cuenta en USD y cotización en USD/USDT (los 4 instrumentos del MVP), por lo que el valor de punto es 1; otra divisa exigiría conversión (fuera de alcance). | Elegido por el usuario (Decimal). Redondear siempre a favor de la seguridad. |
| D61 | **Kelly:** `f* = p − (1 − p)/b`, con `p` = probabilidad de ganar y `b` = ratio ganancia/pérdida; `f* ≤ 0` ⇒ fracción 0. `fraction = min(kelly_fraction · f*, cap)` con `kelly_fraction = 0.25` y `cap = risk_per_trade_pct` por defecto. **Riesgo de ruina:** aproximación `((1 − A)/(1 + A))^N` con ventaja `A = p − (1 − p)/b` y `N = ⌊1 / risk_pct⌋` unidades de riesgo; `1.0` si `A ≤ 0`, acotada a `[0, 1]`. La docstring cita la fórmula y sus supuestos. Entradas fuera de rango (`p ∉ [0,1]`, `b ≤ 0`) lanzan `ValueError` con el dato. | Fórmulas puras con límites, como pide el roadmap. |
| D62 | **Guardas de cartera** (`evaluate_trade(trade, state, correlations, instrument, settings) -> GuardDecision`): se evalúan **todas** y se acumulan los motivos (no se corta en la primera). (a) `INVALID_LEVELS` si el stop está del lado equivocado de la entrada o el TP del lado equivocado; (b) `RR_BELOW_MIN` si `R:R < MIN_RR` (1,8); (c) `DAILY_LOSS_LIMIT` si `realized_pnl_today ≤ −MAX_DAILY_LOSS_PCT · day_start_equity`; (d) `OPEN_RISK_LIMIT` si el riesgo abierto + el nuevo supera `MAX_OPEN_RISK_PCT · equity`; (e) `CORRELATED_RISK_LIMIT` si el riesgo de posiciones abiertas del mismo sentido con `|ρ| ≥ CORRELATION_THRESHOLD` + el nuevo supera `MAX_CORRELATED_RISK_PCT · equity`; (f) `SIZE_BELOW_LOT` (D60). Solo si no hay motivos, `approved = True` y se devuelve el `size`. | Principios 3 y 4. Acumular motivos da trazabilidad al `RiskAuditorAgent` (Fase 3). |
| D63 | **Correlación:** matriz de correlación de Pearson de rendimientos logarítmicos sobre las **últimas `CORRELATION_WINDOW` (100) velas comunes** (unión interna por `ts`) de los instrumentos pedidos, en un timeframe dado. Se calcula en `risk/correlation.py` desde un `dict[str, polars.Series]` y devuelve `dict[tuple[str, str], float]`; un par con menos de 20 observaciones comunes se devuelve como `nan` y las guardas lo tratan como **correlación desconocida ⇒ se asume 1,0 (prudente)**. El servicio que lo carga desde la BD llega con la Fase 3; aquí solo se testea la función pura. | Elegido por el usuario (ventana fija). Pesimista por defecto: ante la duda, se limita más. |
| D64 | **Persistencia del backtest:** cada `POST /quant/backtest` correcto inserta una fila en `strategies`. La curva de capital **no** se guarda en `metrics` (solo se devuelve); se puede regenerar con `params` y los datos. El mismo `BacktestConfig` sobre los mismos datos da el mismo `config_hash` y las mismas métricas. | Trazabilidad (misión §4.5) sin inflar la tabla. |
| D65 | **Los datos del backtest salen de `ohlcv_bars`** (`app/repositories/ohlcv.py`, nueva consulta por rango ascendente). Ningún test llama a la red; los tests usan series sintéticas con semilla fija (`numpy.random.default_rng(seed)`) y velas insertadas con `upsert_candles`. | Elegido por el usuario. |
| D66 | **Layout de código:** `app/quant/{data,features,regime_stats,structure,regime,backtest}.py` y `app/risk/{sizing,kelly,guards,correlation}.py`. `quant/` y `risk/` **no importan** FastAPI, SQLAlchemy ni `httpx`; solo esquemas, polars y numpy. El I/O vive en `services/backtest.py` y `api/v1/quant.py`. `mypy --strict` pasa en todo `app/` (override `ignore_missing_imports` para `statsmodels.*`). | Núcleo puro y testeable; coincide con `tech-stack.md` §8. |
| D67 | **Clasificador de régimen** (precedencia): (1) `n_obs < min_obs` → `ValueError` en español; (2) `volatility_ratio ≥ vol_ratio_high` → `HIGH_VOLATILITY_NOISE`; (3) `hurst < hurst_mean_reverting` **y** `adf_pvalue < adf_alpha` → `MEAN_REVERTING`; (4) `hurst > hurst_trending` → `TRENDING`; (5) cualquier otro caso (inconcluyente) → `HIGH_VOLATILITY_NOISE`. `volatility_ratio` = volatilidad móvil corta (20) / volatilidad larga (100) de los log-retornos. Los umbrales viajan en el resultado. | Reglas explícitas y auditables; «inconcluyente = ruido» es la opción prudente y se documenta en la docstring. |
| D68 | **Estructura de mercado:** swing alto si `high` es el máximo estricto de `[i−n, i+n]` (análogo para el bajo). **BOS:** cierre por encima del último swing alto confirmado en tendencia alcista (o por debajo del swing bajo en bajista), es decir, continuación. **CHoCH:** cierre que rompe el último swing en sentido contrario a la tendencia vigente. La tendencia inicial es indefinida y la fija la primera ruptura. **FVG alcista:** `low[i+1] > high[i−1]`, zona `[high[i−1], low[i+1]]`; **bajista:** `high[i+1] < low[i−1]`. Se marca `mitigated_at` en la primera vela posterior que entra en la zona. | Definiciones operativas únicas; los fixtures de 2.3 las fijan con resultados esperados. |
| D69 | **Datos insuficientes → 422, nunca un resultado engañoso.** El backtest exige `n_bars ≥ zscore_window + 2` y `n_bars ≤ BACKTEST_MAX_BARS`; si no, `detail` dice p. ej. «Datos insuficientes para EUR/USD 15m: 38 velas, se necesitan al menos 52.». Si no hay ninguna operación, se devuelve el resultado con `n_trades = 0`, métricas en 0 y un aviso en `warnings`. | Honestidad ante datos escasos (misión: no esconder fallos). |

## 4. Variables de entorno (backend, nuevas)

Todas opcionales, con estos valores por defecto en `Settings` y en `backend/.env.example`. Los porcentajes son `Decimal` en unidades de porcentaje (`1.0` = 1 %).

```dotenv
RISK_PER_TRADE_PCT=1.0            # riesgo máximo por operación (misión §4.4)
MAX_DAILY_LOSS_PCT=3.0            # pérdida diaria máxima (misión §4.4)
MIN_RR=1.8                        # R:R mínimo; por debajo, veto
KELLY_FRACTION=0.25               # fracción de Kelly aplicada
MAX_OPEN_RISK_PCT=3.0             # riesgo abierto total máximo
MAX_CORRELATED_RISK_PCT=2.0       # riesgo máximo en posiciones correlacionadas del mismo sentido
CORRELATION_WINDOW=100            # velas comunes para la matriz de correlación
CORRELATION_THRESHOLD=0.7         # |ρ| a partir del cual dos posiciones cuentan como correlacionadas
BACKTEST_MAX_BARS=50000           # tope de velas por backtest
```

Ninguna es un secreto. `get_settings()` valida los rangos (p. ej. `0 < RISK_PER_TRADE_PCT ≤ 5`, `MIN_RR ≥ 1`).

## 5. Contexto, tono y patrones a seguir

- **Sin texto de UI.** El texto visible es el `detail` de la API y los `messages` de `GuardDecision`: en **español**, técnicos, con el dato incumplido (p. ej. `"R:R 1.42 por debajo del mínimo 1.8"`, `"Pérdida diaria −3.2 % alcanza el límite de 3.0 %"`). No esconden fallos ni suavizan un veto.
- **Esquemas primero:** el grupo 2 del plan escribe todos los esquemas y sus tests antes de tocar la lógica.
- **Patrones existentes:** sesión con `get_session` de [`app/core/db.py`](../../backend/app/core/db.py); `get_settings()` de [`app/core/config.py`](../../backend/app/core/config.py); enums y `Timeframe.floor/duration` en [`app/schemas/enums.py`](../../backend/app/schemas/enums.py); CHECK de enums con [`app/models/checks.py`](../../backend/app/models/checks.py); modelo de referencia [`app/models/trade_signal.py`](../../backend/app/models/trade_signal.py); repositorio [`app/repositories/ohlcv.py`](../../backend/app/repositories/ohlcv.py); router en [`app/api/v1/router.py`](../../backend/app/api/v1/router.py); tests `db` con `@pytest.mark.db` y [`tests/conftest.py`](../../backend/tests/conftest.py).
- **Tests:** `hypothesis` para las propiedades de riesgo (nunca se supera el 1 %, `0 ≤ fracción ≤ cap`, RoR en `[0, 1]`); valores de referencia calculados a mano para features; series sintéticas para régimen; fixtures de velas para estructura; *golden* para el backtester. Ningún test llama a la red.
- **Fuente de verdad:** si esta spec contradice `tech-stack.md`, prevalece `tech-stack.md`.
- **Sin `tech-stack.md` nuevo** salvo el changelog de las dependencias añadidas (D54).

## 6. Preguntas abiertas y riesgos

| Tema | Estado | Qué hacer |
| :--- | :--- | :--- |
| Aprobación de dependencias (D54) | **Resuelta** (2026-11-13). | Aprobadas `polars`, `numpy`, `statsmodels` y `hypothesis` (dev). |
| Costes y *slippage* | **Fuera de alcance.** | El backtest no los modela, por lo que el Sharpe es optimista; `BacktestMetricsSchema.warnings` lo indica siempre. Añadir `fee_bps`/`slippage_bps` en una fase posterior es compatible hacia atrás. |
| Umbrales de régimen (D67) y tamaño de ventana de swings (D68) | Valores iniciales razonables, **sin calibrar con datos reales**. | Calibrar en la Fase 3 al ver los agentes consumirlos; se cambian solo en `RegimeThresholds`. |
| Datos de Yahoo (FX, XAU, NAS100) | Provisionales (spec del proveedor). | El backtest lleva el aviso en `warnings` si el símbolo es `YAHOO`; NAS100 solo tiene `5m`, `15m` y `1d`. Historia de `5m`/`15m` ~59 días: puede dar «datos insuficientes» (D69). |
| Estimaciones de Hurst/ADF en muestras cortas | Riesgo conocido. | `min_obs = 100`; el resultado incluye `n_obs`; los tests documentan el comportamiento con series sintéticas de 1000 puntos. |
| Rendimiento del backtester | Riesgo bajo. | Vectorizado; tope `BACKTEST_MAX_BARS`. Se mide con 50 000 velas en el smoke manual. |
| Valor de punto fuera de USD | Limitación aceptada (D60). | Documentada en la docstring de `sizing.py`; revisar si se añaden instrumentos no cotizados en USD. |
