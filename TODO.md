# TODO

[ ] Phase 1: Core Data & Schema Foundation (Week 1)

Implement PostgreSQL models (instruments, ohlcv_bars, trade_signals) and Alembic migrations.

Build unified market data ingestion adapters for BTC/USDT (Crypto), EUR/USD & XAU/USD (Forex), and NAS100 (Indices).

[ ] Phase 2: Quant Engine & Deterministic Risk Core (Week 2)

Implement vectorized technical & statistical feature extractors (ATR, Market Structure, Z-Score, Hurst Exponent).

Build the deterministic Position Sizing & Risk-of-Ruin calculator.

[ ] Phase 3: Multi-Agent Orchestration (Week 3)

Wire MarketStructureAgent, QuantAlphaAgent, and RiskAuditorAgent with strict Pydantic structured outputs.

Persist full reasoning traces in PostgreSQL JSONB columns for auditability.

[ ] Phase 4: Next.js Institutional Terminal UI (Week 4)

Integrate lightweight-charts with automated overlay rendering (Entry zones, Stop Loss, Take Profit, FVG boxes).

Build the live Agent Reasoning Feed and Paper Trading Execution Blotter.