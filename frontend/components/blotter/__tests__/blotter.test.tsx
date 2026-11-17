import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Blotter } from "@/components/blotter/blotter";
import { apiGet, apiPost, ApiError } from "@/lib/api";
import type { components } from "@/types/api";

vi.mock("@/lib/api", () => {
  class MockApiError extends Error {
    constructor(
      public readonly status: number,
      public readonly detail: string,
    ) {
      super(detail);
    }
  }
  return { apiGet: vi.fn(), apiPost: vi.fn(), ApiError: MockApiError };
});

type BlotterSchema = components["schemas"]["BlotterSchema"];
type PaperOrderSchema = components["schemas"]["PaperOrderSchema"];

const baseOrder: PaperOrderSchema = {
  order_id: "o1",
  signal_id: "s1",
  symbol: "BTC/USDT",
  timeframe: "1h",
  direction: "LONG",
  executed_at: "2024-01-15T10:00:00Z",
  signal_entry: "50000.00",
  stop_loss: "49000.00",
  take_profit: "52000.00",
  units: "0.02000",
  risk_amount: "100.00",
  status: "CLOSED_TP",
  fill_price: "50000.123",
  exit_price: "52000.456",
  pnl: "40.00",
  realized_pnl: "40.00",
  r_multiple: "0.40",
  simulated: true,
  warnings: [],
};

const baseBlotter: BlotterSchema = {
  equity: "10040.00",
  day_start_equity: "10000.00",
  realized_pnl_today: "40.00",
  realized_pnl_total: "40.00",
  unrealized_pnl_total: "12.50",
  open_risk: "250.00",
  daily_loss_limit_reached: false,
  orders: [baseOrder],
  warnings: [],
};

function renderBlotter() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return render(<Blotter tickSizes={{ "BTC/USDT": "0.01" }} lotSizes={{ "BTC/USDT": "0.001" }} />, {
    wrapper: Wrapper,
  });
}

describe("Blotter", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset();
    vi.mocked(apiPost).mockReset();
  });

  it("muestra la tabla con formato de tick_size, el resumen y los avisos", async () => {
    vi.mocked(apiGet).mockResolvedValue(baseBlotter);
    renderBlotter();

    const table = await screen.findByRole("table");
    for (const header of ["Símbolo", "Dirección", "Unidades", "Estado", "Fill", "Salida", "PnL", "R"]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    expect(table).toHaveTextContent("BTC/USDT");
    expect(table).toHaveTextContent("LONG");
    expect(table).toHaveTextContent("0.020");
    expect(table).toHaveTextContent("CLOSED_TP");
    expect(table).toHaveTextContent("50000.12");
    expect(table).toHaveTextContent("52000.46");
    expect(table).toHaveTextContent("40.00");
    expect(table).toHaveTextContent("0.40");

    expect(screen.getByText("Equity")).toBeInTheDocument();
    expect(screen.getByText("10040.00")).toBeInTheDocument();
    expect(screen.getByText("PnL del día")).toBeInTheDocument();
    expect(screen.getByText("PnL no realizado")).toBeInTheDocument();
    expect(screen.getByText("12.50")).toBeInTheDocument();
    expect(screen.getByText("Riesgo abierto")).toBeInTheDocument();
    expect(screen.getByText("250.00")).toBeInTheDocument();

    expect(screen.getByText("Paper trading simulado: sin costes ni slippage")).toBeInTheDocument();
    expect(
      screen.getByText("PnL no realizado = vs. último cierre ingerido (no es tiempo real)"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Límite de pérdida diaria alcanzado/)).not.toBeInTheDocument();
  });

  it("muestra PENDING_FILL con su explicación y «—» para valores nulos", async () => {
    vi.mocked(apiGet).mockResolvedValue({
      ...baseBlotter,
      orders: [
        {
          ...baseOrder,
          status: "PENDING_FILL",
          fill_price: null,
          exit_price: null,
          pnl: null,
          realized_pnl: null,
          r_multiple: null,
        },
      ],
    });
    renderBlotter();

    const table = await screen.findByRole("table");
    expect(table).toHaveTextContent("PENDING_FILL");
    expect(screen.getAllByText("—")).toHaveLength(4);
    expect(screen.getByText(/aún espera una vela posterior/)).toBeInTheDocument();
  });

  it("avisa cuando se alcanzó el límite de pérdida diaria", async () => {
    vi.mocked(apiGet).mockResolvedValue({ ...baseBlotter, daily_loss_limit_reached: true });
    renderBlotter();
    expect(await screen.findByText(/Límite de pérdida diaria alcanzado/)).toBeInTheDocument();
  });

  it("muestra el estado vacío", async () => {
    vi.mocked(apiGet).mockResolvedValue({ ...baseBlotter, orders: [] });
    renderBlotter();
    expect(
      await screen.findByText("Sin órdenes simuladas. Ejecuta una señal aprobada."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("«Actualizar» llama a POST /paper/refresh", async () => {
    vi.mocked(apiGet).mockResolvedValue(baseBlotter);
    vi.mocked(apiPost).mockResolvedValue({
      orders_checked: 1,
      orders_filled: 0,
      orders_closed: 0,
      warnings: [],
    });
    renderBlotter();

    fireEvent.click(await screen.findByRole("button", { name: "Actualizar" }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/api/v1/paper/refresh"));
  });

  it("muestra el error 5xx y permite reintentar", async () => {
    vi.mocked(apiGet).mockRejectedValueOnce(new ApiError(500, "Error interno del servidor"));
    vi.mocked(apiGet).mockResolvedValueOnce(baseBlotter);
    renderBlotter();

    expect(await screen.findByText("Error interno del servidor")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });
});
