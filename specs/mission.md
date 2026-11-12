# Misión — QuantAgentic Terminal

> Documento constitucional. Ante cualquier duda de alcance, prioridad o diseño, prevalece este documento. Los cambios se hacen de forma explícita y se registran en el changelog al final.

## 1. Declaración de misión

**Construir un terminal personal de investigación cuantitativa en el que agentes de IA generan hipótesis de trading auditables, mientras que todo cálculo de riesgo, tamaño de posición y métrica de rendimiento lo realiza código determinista. Las señales resultantes se validan con backtesting y se ejecutan solo en paper trading.**

El MVP pretende ganar dinero en real. Y además pretende responder con rigor a una pregunta: *¿producen los agentes señales con valor esperado positivo, y puedo auditar por qué las produjeron?*

## 2. Público objetivo

| Aspecto | Definición |
| :--- | :--- |
| **Usuario único** | El propio autor, en su doble papel de trader y desarrollador. |
| **Perfil** | Programa (Python/TypeScript) y conoce conceptos cuantitativos (Hurst, Z-score, Kelly, Sharpe) y de estructura de mercado (BOS, CHoCH, FVG, liquidez). |
| **Contexto de uso** | Estación local en Linux, con PostgreSQL local. Sin despliegue público. |
| **Implicaciones** | Sin autenticación ni multiusuario ni onboarding. La interfaz puede ser densa y técnica. Se prioriza la trazabilidad y la reproducibilidad sobre el acabado visual. |

## 3. Alcance del MVP

### Dentro del alcance
- **Mercados:** cripto (BTC/USDT vía ccxt), Forex (EUR/USD, XAU/USD vía OANDA) e índices (NAS100 vía OANDA).
- **Marcos temporales:** 15m, 1H, 4H y 1D.
- **Agentes:** `MarketStructureAgent`, `QuantAlphaAgent` y `RiskAuditorAgent`, con salidas Pydantic estrictas.
- **Motor cuantitativo:** indicadores y estadísticos vectorizados, backtester determinista y calculadora de tamaño de posición y riesgo de ruina.
- **Ejecución:** **solo paper trading**, con un blotter simulado.
- **Auditoría:** traza completa del razonamiento de cada ejecución de agente, persistida en JSONB.
- **UI:** gráfico con overlays (entrada, SL, TP, FVG), feed de razonamiento de agentes y blotter.

### Fuera del alcance (MVP)
- Ejecución con capital real, aunque sea con confirmación humana (HITL); también las órdenes en testnet de los exchanges.
- Autenticación, multiusuario, roles y facturación.
- `MacroSentimentAgent`: aparece en el diagrama del README, pero se aplaza a después del MVP.
- Libros de órdenes (orderbook) y análisis de flujo de órdenes de alta frecuencia.
- Despliegue en la nube y contenedorización.

## 4. Principios no negociables

1. **Esquemas primero (SDD).** No se implementa ningún endpoint, herramienta de agente ni componente de UI sin que exista antes su contrato Pydantic. Los tipos TypeScript se **generan** desde OpenAPI y nunca se escriben a mano.
2. **El LLM nunca calcula riesgo.** Tamaño de posición, fracción de Kelly, Sharpe, drawdown y R:R se calculan con Python puro (numpy/scipy/polars). El LLM solo sintetiza patrones, interpreta regímenes y formula hipótesis.
3. **Veto determinista.** Una señal con R:R < 1,8 o que haga superar los límites de riesgo de la cartera se rechaza en código, antes y con independencia de la opinión del `RiskAuditorAgent`.
4. **Circuit breakers:**
   - Riesgo máximo por operación: **1,0 %** del capital (configurable).
   - Pérdida diaria máxima: **3,0 %**. Al alcanzarla se desactiva la ejecución de señales durante el resto del día.
5. **Auditabilidad total.** Cada análisis de agente (entradas, salidas, modelo, prompt, tokens y latencia) se persiste de forma inmutable.
6. **Reproducibilidad.** Con los mismos datos y la misma configuración, un backtest devuelve exactamente las mismas métricas. Hay tests que lo verifican.
7. **Incrementos pequeños.** Cada fase del roadmap se entrega funcionando y con tests antes de pasar a la siguiente.

## 5. Criterios de éxito del MVP

- [ ] Ingesta de OHLCV histórica e incremental para los 4 instrumentos y los 4 marcos temporales.
- [ ] Backtest determinista con métricas (Sharpe, max drawdown, win rate, expectancy) reproducibles en los tests.
- [ ] Flujo `POST /agents/analyze` de extremo a extremo que produzca un `TradeSignalSchema` válido o un veto justificado.
- [ ] Toda señal aprobada respeta los circuit breakers, verificado con tests de propiedades y de límites.
- [ ] El terminal muestra el gráfico con overlays, el feed de razonamiento en streaming y el blotter de paper trading.
- [ ] Hay un diario (journal) que permite comparar las señales emitidas con su resultado simulado.

## Changelog

- **2026-11-12:** versión inicial, redactada a partir de la entrevista con el autor (alcance: herramienta personal, paper trading, cripto + FX + índices).
