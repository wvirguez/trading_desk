import type { components } from "../../types/api";
import { loadFixture } from "./fixtures";

type TradeSignal = components["schemas"]["TradeSignalSchema"];
type PaperOrder = components["schemas"]["PaperOrderSchema"];
type OrderReceipt = components["schemas"]["OrderReceiptSchema"];
type Blotter = components["schemas"]["BlotterSchema"];
type Journal = components["schemas"]["JournalSchema"];
type JournalEntry = components["schemas"]["JournalEntrySchema"];
type JournalOutcome = components["schemas"]["JournalOutcome"];
type RefreshResult = components["schemas"]["PaperRefreshResult"];

interface PaperScenario {
  initial_equity: string;
  order_id: string;
  executed_at: string;
  filled_at: string;
  closed_at: string;
  fill_price: string;
  exit_price: string;
  pnl: string;
  r_multiple: string;
  duplicate_detail: string;
  daily_loss_detail: string;
}

const scenario = loadFixture<PaperScenario>("paper-scenario.json");

export interface PaperStateOptions {
  signals: TradeSignal[];
  /** Si es true, ejecutar una señal devuelve 409 por el veto de pérdida diaria. */
  dailyLossVeto?: boolean;
}

export type ExecuteOutcome =
  | { ok: true; receipt: OrderReceipt }
  | { ok: false; status: 404 | 409; detail: string };

/**
 * Estado en memoria de una prueba (D144): señales, órdenes simuladas, blotter y diario.
 * Cada llamada a `installRestMocks` crea el suyo, así que las pruebas no se contaminan.
 */
export class PaperState {
  private signals: TradeSignal[];
  private orders: PaperOrder[] = [];
  private readonly dailyLossVeto: boolean;

  constructor(options: PaperStateOptions) {
    this.signals = options.signals.map((signal) => ({ ...signal }));
    this.dailyLossVeto = options.dailyLossVeto ?? false;
  }

  addSignal(signal: TradeSignal): void {
    if (!this.signals.some((existing) => existing.id === signal.id)) {
      this.signals.push({ ...signal });
    }
  }

  activeSignals(): TradeSignal[] {
    return this.signals.filter((signal) => signal.status === "APPROVED");
  }

  execute(signalId: string): ExecuteOutcome {
    const signal = this.signals.find((item) => item.id === signalId);
    if (!signal) {
      return { ok: false, status: 404, detail: `Señal ${signalId} no encontrada.` };
    }
    if (signal.status === "EXECUTED") {
      return { ok: false, status: 409, detail: scenario.duplicate_detail };
    }
    if (signal.status !== "APPROVED") {
      return { ok: false, status: 409, detail: `La señal ${signalId} no está aprobada.` };
    }
    if (this.dailyLossVeto) {
      return { ok: false, status: 409, detail: scenario.daily_loss_detail };
    }

    signal.status = "EXECUTED";
    const order: PaperOrder = {
      order_id: scenario.order_id,
      signal_id: signal.id,
      symbol: signal.symbol,
      timeframe: signal.timeframe,
      direction: signal.direction,
      units: signal.size?.units ?? "0.10000",
      risk_amount: signal.size?.risk_amount ?? "33.63",
      signal_entry: signal.entry,
      stop_loss: signal.stop_loss,
      take_profit: signal.take_profit,
      status: "PENDING_FILL",
      executed_at: scenario.executed_at,
      simulated: true,
      warnings: [],
    };
    this.orders.push(order);
    const receipt: OrderReceipt = {
      order_id: order.order_id,
      signal_id: order.signal_id,
      symbol: order.symbol,
      timeframe: order.timeframe,
      direction: order.direction,
      units: order.units,
      risk_amount: order.risk_amount,
      signal_entry: order.signal_entry,
      stop_loss: order.stop_loss,
      take_profit: order.take_profit,
      status: order.status,
      executed_at: order.executed_at,
      simulated: true,
      warnings: [],
    };
    return { ok: true, receipt };
  }

  /** Segunda fase: las órdenes pendientes se rellenan y cierran por TP. */
  refresh(): RefreshResult {
    let closed = 0;
    let filled = 0;
    const checked = this.orders.filter(
      (order) => order.status === "PENDING_FILL" || order.status === "OPEN",
    );
    for (const order of checked) {
      if (order.status === "PENDING_FILL") filled += 1;
      order.status = "CLOSED_TP";
      order.fill_price = scenario.fill_price;
      order.filled_at = scenario.filled_at;
      order.exit_price = scenario.exit_price;
      order.closed_at = scenario.closed_at;
      order.realized_pnl = scenario.pnl;
      order.pnl = scenario.pnl;
      order.r_multiple = scenario.r_multiple;
      closed += 1;
    }
    return {
      orders_checked: checked.length,
      orders_filled: filled,
      orders_closed: closed,
      warnings: [],
    };
  }

  blotter(status: string | null): Blotter {
    const closedPnl = this.orders
      .filter((order) => order.status === "CLOSED_TP" || order.status === "CLOSED_SL")
      .reduce((sum, order) => sum + Number(order.realized_pnl ?? 0), 0);
    const openRisk = this.orders
      .filter((order) => order.status === "PENDING_FILL" || order.status === "OPEN")
      .reduce((sum, order) => sum + Number(order.risk_amount), 0);
    const equity = Number(scenario.initial_equity) + closedPnl;
    return {
      daily_loss_limit_reached: this.dailyLossVeto,
      day_start_equity: scenario.initial_equity,
      equity: equity.toFixed(2),
      open_risk: openRisk.toFixed(2),
      realized_pnl_today: closedPnl.toFixed(2),
      realized_pnl_total: closedPnl.toFixed(2),
      unrealized_pnl_total: "0.00",
      orders: this.orders.filter((order) => !status || order.status === status),
      warnings: [],
    };
  }

  journal(symbol: string | null): Journal {
    const entries: JournalEntry[] = this.signals
      .filter((signal) => !symbol || signal.symbol === symbol)
      .map((signal) => {
        const order = this.orders.find((item) => item.signal_id === signal.id);
        let outcome: JournalOutcome = "NOT_EXECUTED";
        if (order) {
          if (order.status === "PENDING_FILL") outcome = "PENDING_FILL";
          else if (order.status === "OPEN") outcome = "OPEN";
          else outcome = Number(order.realized_pnl ?? 0) > 0 ? "WIN" : "LOSS";
        }
        return {
          signal_id: signal.id,
          analysis_id: signal.analysis_id,
          symbol: signal.symbol,
          timeframe: signal.timeframe,
          direction: signal.direction,
          entry: signal.entry,
          stop_loss: signal.stop_loss,
          take_profit: signal.take_profit,
          rr: signal.rr,
          rationale: signal.rationale,
          regime: signal.regime,
          signal_status: signal.status,
          veto_reasons: signal.veto_reasons,
          created_at: signal.created_at,
          outcome,
          order_id: order?.order_id ?? null,
          fill_price: order?.fill_price ?? null,
          exit_price: order?.exit_price ?? null,
          closed_at: order?.closed_at ?? null,
          realized_pnl: order?.realized_pnl ?? null,
          r_multiple: order?.r_multiple ?? null,
          risk_amount: order?.risk_amount ?? null,
        };
      });

    const wins = entries.filter((entry) => entry.outcome === "WIN").length;
    const losses = entries.filter((entry) => entry.outcome === "LOSS").length;
    const closed = wins + losses;
    const realized = entries
      .filter((entry) => entry.r_multiple)
      .map((entry) => Number(entry.r_multiple));
    const avgR =
      realized.length > 0 ? realized.reduce((a, b) => a + b, 0) / realized.length : null;
    const totalPnl = entries.reduce((sum, entry) => sum + Number(entry.realized_pnl ?? 0), 0);

    return {
      entries,
      summary: {
        n_signals: entries.length,
        n_approved: entries.filter((entry) => entry.signal_status === "APPROVED").length,
        n_rejected: entries.filter((entry) => entry.signal_status === "REJECTED").length,
        n_executed: entries.filter((entry) => entry.signal_status === "EXECUTED").length,
        n_closed: closed,
        n_wins: wins,
        n_losses: losses,
        win_rate: closed > 0 ? wins / closed : null,
        total_pnl: totalPnl.toFixed(2),
        avg_rr_emitted:
          entries.length > 0
            ? entries.reduce((sum, entry) => sum + Number(entry.rr), 0) / entries.length
            : null,
        avg_r_realized: avgR,
        expectancy_r: avgR,
        warnings: [],
      },
    };
  }
}
