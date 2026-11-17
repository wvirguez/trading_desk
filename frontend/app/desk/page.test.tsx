import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import DeskPage from "./page";

const appState = vi.hoisted(() => ({
  status: "running" as "running" | "completed",
}));

vi.mock("@/store/terminal", () => {
  const store = Object.assign(
    () => ({ symbol: "BTC/USDT", timeframe: "1h" }),
    { getState: () => ({ instruments: [] }) },
  );
  return { useTerminalStore: store };
});

vi.mock("@/hooks/use-analysis", () => ({
  useAnalysis: () => ({
    state: {
      analysisId: null,
      symbol: "BTC/USDT",
      timeframe: "1h",
      timeframes: [],
      status: appState.status,
      steps: [],
      totalUsage: { inputTokens: 0, outputTokens: 0, latencyMs: 0, costUsd: null },
      warnings: [],
      outcome: null,
      report: null,
      error: null,
      failedStep: null,
      canRetry: false,
      lastSeq: 0,
    },
    start: vi.fn(),
    cancel: vi.fn(),
    reset: vi.fn(),
  }),
}));

vi.mock("@/hooks/use-signals", () => ({
  useActiveSignals: () => ({ data: [] }),
}));

vi.mock("@/hooks/use-structure", () => ({
  useStructure: () => ({ data: null }),
}));

vi.mock("@/components/chart/symbol-select", () => ({
  default: () => <div data-testid="symbol-select" />,
}));
vi.mock("@/components/chart/timeframe-select", () => ({
  default: () => <div data-testid="timeframe-select" />,
}));
vi.mock("@/components/chart/candle-chart", () => ({
  default: () => <div data-testid="candle-chart" />,
}));
vi.mock("@/components/signals/signal-list", () => ({
  SignalList: () => <div data-testid="signal-list" />,
}));
vi.mock("@/components/blotter/blotter", () => ({
  Blotter: () => <div data-testid="blotter" />,
}));
vi.mock("@/components/agents/analysis-form", () => ({
  default: () => <div data-testid="analysis-form" />,
}));
vi.mock("@/components/agents/analysis-feed", () => ({
  default: () => <div data-testid="analysis-feed" />,
}));

vi.mock("@/components/ui/tabs", () => ({
  Tabs: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  TabsList: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  TabsContent: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/components/ui/separator", () => ({
  Separator: () => <span />,
}));
vi.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
}));

function renderPage(queryClient: QueryClient) {
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "Wrapper";
  return render(<DeskPage />, { wrapper: Wrapper });
}

describe("app/desk/page.tsx", () => {
  beforeEach(() => {
    appState.status = "running";
  });

  it("invalida la consulta real de señales activas al completar un análisis", async () => {
    const queryClient = new QueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const view = renderPage(queryClient);
    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ["active-signals"] });

    appState.status = "completed";
    view.rerender(
      <QueryClientProvider client={queryClient}>
        <DeskPage />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["active-signals"] });
    });
  });
});
