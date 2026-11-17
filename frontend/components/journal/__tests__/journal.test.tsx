import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import JournalSummary from "../journal-summary";
import JournalTable from "../journal-table";
import JournalPage from "@/app/journal/page";
import type { components } from "@/types/api";

type Entry = components["schemas"]["JournalEntrySchema"];
type Summary = components["schemas"]["JournalSummarySchema"];

vi.mock("next/navigation", () => ({ usePathname: () => "/journal" }));
vi.mock("@/components/shell/topbar", () => ({ default: () => <div data-testid="topbar" /> }));
vi.mock("@/lib/env", () => ({ getApiUrl: () => "http://localhost:8000" }));

const SUMMARY: Summary = {
  n_signals: 3,
  n_approved: 1,
  n_rejected: 1,
  n_executed: 1,
  n_closed: 1,
  n_wins: 1,
  n_losses: 0,
  win_rate: 1,
  total_pnl: "150.5",
  avg_rr_emitted: 2.5,
  avg_r_realized: 1.8,
  expectancy_r: 1.8,
  warnings: ["Muestra pequeña: menos de 30 operaciones cerradas"],
};

const NULL_SUMMARY: Summary = {
  ...SUMMARY,
  n_closed: 0,
  n_wins: 0,
  win_rate: null,
  avg_rr_emitted: null,
  avg_r_realized: null,
  expectancy_r: null,
  warnings: [],
};

const base = {
  analysis_id: "a1",
  created_at: "2026-11-16T00:00:00Z",
  direction: "LONG" as const,
  regime: "TRENDING" as const,
  timeframe: "1h" as const,
  veto_reasons: [],
};

const ENTRIES: Entry[] = [
  {
    ...base,
    signal_id: "s1",
    symbol: "BTC/USDT",
    signal_status: "EXECUTED",
    outcome: "WIN",
    entry: "50000.123",
    stop_loss: "49000",
    take_profit: "52000",
    rr: "2.5",
    r_multiple: "1.8",
    order_id: "o1",
    rationale: "Razonamiento del modelo",
  },
  {
    ...base,
    signal_id: "s2",
    symbol: "BTC/USDT",
    signal_status: "REJECTED",
    outcome: "NOT_EXECUTED",
    entry: "50000",
    stop_loss: "49000",
    take_profit: "50500",
    rr: "0.5",
    veto_reasons: ["RR_BELOW_MIN", "DAILY_LOSS_LIMIT"],
    rationale: "Otro texto",
  },
];

describe("JournalSummary", () => {
  it("muestra métricas, comparación R:R vs R, avisos y descargo", () => {
    render(<JournalSummary summary={SUMMARY} />);
    expect(screen.getByText("R:R emitido")).toBeInTheDocument();
    expect(screen.getByText("R realizado")).toBeInTheDocument();
    expect(screen.getByText("2.50")).toBeInTheDocument();
    expect(screen.getAllByText("1.80", { selector: "dd" })).toHaveLength(2);
    expect(screen.getByText("100.00 %")).toBeInTheDocument();
    expect(screen.getByText("150.50")).toBeInTheDocument();
    expect(screen.getByText(/Muestra pequeña/)).toBeInTheDocument();
    expect(screen.getByText(/ayuda de análisis, no una promesa de rentabilidad/)).toBeInTheDocument();
  });

  it("muestra — con métricas nulas", () => {
    render(<JournalSummary summary={NULL_SUMMARY} />);
    expect(screen.getAllByText("—")).toHaveLength(4);
  });
});

describe("JournalTable", () => {
  it("una fila por señal con estado, outcome, niveles y R", () => {
    render(<JournalTable entries={ENTRIES} tickSizes={{ "BTC/USDT": "0.01" }} />);
    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(screen.getByText("EXECUTED")).toBeInTheDocument();
    expect(screen.getByText("WIN")).toBeInTheDocument();
    expect(screen.getByText("50000.12")).toBeInTheDocument();
    expect(screen.getByText("1.80")).toBeInTheDocument();
    expect(screen.getByText("RR_BELOW_MIN, DAILY_LOSS_LIMIT")).toBeInTheDocument();
  });

  it("despliega el rationale con la etiqueta de no verificado", () => {
    render(<JournalTable entries={ENTRIES} tickSizes={{}} />);
    expect(screen.queryByText("Razonamiento del modelo")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Ver texto" })[0]);
    expect(screen.getByText("Razonamiento del modelo")).toBeInTheDocument();
    expect(screen.getByText("Texto del modelo, no verificado")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ocultar texto" }));
    expect(screen.queryByText("Razonamiento del modelo")).not.toBeInTheDocument();
  });

  it("estado vacío", () => {
    render(<JournalTable entries={[]} tickSizes={{}} />);
    expect(screen.getByText("Sin señales registradas. Lanza un análisis en /agents.")).toBeInTheDocument();
  });
});

describe("/journal", () => {
  const mockFetch = vi.fn();
  beforeEach(() => {
    mockFetch.mockReset();
    mockFetch.mockImplementation(async (url: string) => {
      if (url.includes("/market/instruments")) {
        return {
          ok: true,
          json: async () => [{ symbol: "BTC/USDT", tick_size: "0.01" }, { symbol: "ETH/USDT", tick_size: "0.01" }],
        };
      }
      return { ok: true, json: async () => ({ entries: ENTRIES, summary: SUMMARY }) };
    });
    vi.stubGlobal("fetch", mockFetch);
  });
  afterEach(() => vi.unstubAllGlobals());

  function renderPage(ui: ReactNode) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  }

  it("ya no muestra «Pendiente», lista el diario y filtra por símbolo", async () => {
    renderPage(<JournalPage />);
    expect(screen.queryByText(/Pendiente/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("WIN")).toBeInTheDocument());

    await waitFor(() => expect(screen.getByRole("option", { name: "ETH/USDT" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Símbolo"), { target: { value: "ETH/USDT" } });
    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/journal?symbol=ETH%2FUSDT&limit=100",
        expect.anything(),
      ),
    );
  });

  it("muestra el detail de un error", async () => {
    mockFetch.mockImplementation(async (url: string) =>
      url.includes("/journal")
        ? { ok: false, status: 404, json: async () => ({ detail: "Instrumento desconocido" }) }
        : { ok: true, json: async () => [] },
    );
    renderPage(<JournalPage />);
    expect(await screen.findByText("Instrumento desconocido")).toBeInTheDocument();
  });
});
