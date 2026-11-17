import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useExecuteSignal } from "../use-execute-signal";
import { useBlotter } from "../use-blotter";
import { useRefreshOrders } from "../use-refresh-orders";

vi.mock("@/lib/env", () => ({
  getApiUrl: () => "http://localhost:8000",
}));

const mockFetch = vi.fn();

beforeEach(() => {
  mockFetch.mockReset();
  vi.stubGlobal("fetch", mockFetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, Wrapper };
}

const SIGNAL_ID = "123e4567-e89b-12d3-a456-426614174000";

describe("useExecuteSignal", () => {
  it("hace POST a /signals/{id}/execute e invalida señales activas y blotter", async () => {
    const receipt = { order_id: "o1", status: "PENDING_FILL" };
    mockFetch.mockResolvedValue({ ok: true, json: async () => receipt });
    const { queryClient, Wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useExecuteSignal(), { wrapper: Wrapper });

    await act(async () => {
      await result.current.mutateAsync(SIGNAL_ID);
    });

    expect(mockFetch).toHaveBeenCalledWith(
      `http://localhost:8000/api/v1/signals/${SIGNAL_ID}/execute`,
      expect.objectContaining({ method: "POST" }),
    );
    expect(spy).toHaveBeenCalledWith({ queryKey: ["active-signals"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["blotter"] });
  });

  it.each([
    [404, "Señal 123 no encontrada"],
    [409, "Operación vetada: DAILY_LOSS_LIMIT. Límite de pérdida diaria alcanzado"],
    [422, "Identificador de señal inválido"],
  ])("un %i devuelve el detail exacto como ApiError", async (status, detail) => {
    mockFetch.mockResolvedValue({ ok: false, status, json: async () => ({ detail }) });
    const { queryClient, Wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useExecuteSignal(), { wrapper: Wrapper });

    await act(async () => {
      await result.current.mutateAsync(SIGNAL_ID).catch(() => undefined);
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.name).toBe("ApiError");
    expect(result.current.error?.status).toBe(status);
    expect(result.current.error?.detail).toBe(detail);
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("useBlotter", () => {
  it("hace GET a /paper/blotter sin filtro", async () => {
    const blotter = { equity: "10000.00", orders: [] };
    mockFetch.mockResolvedValue({ ok: true, json: async () => blotter });
    const { Wrapper } = setup();
    const { result } = renderHook(() => useBlotter(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(blotter);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/paper/blotter",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("pasa el estado como query param", async () => {
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({ orders: [] }) });
    const { Wrapper } = setup();
    const { result } = renderHook(() => useBlotter("OPEN"), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockFetch.mock.calls[0][0]).toBe("http://localhost:8000/api/v1/paper/blotter?status=OPEN");
  });

  it("expone el error 5xx", async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 500, json: async () => ({ detail: "Fallo interno" }) });
    const { Wrapper } = setup();
    const { result } = renderHook(() => useBlotter(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.detail).toBe("Fallo interno");
  });
});

describe("useRefreshOrders", () => {
  it("hace POST a /paper/refresh e invalida el blotter", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ orders_checked: 1, orders_filled: 1, orders_closed: 0, warnings: [] }),
    });
    const { queryClient, Wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useRefreshOrders(), { wrapper: Wrapper });

    await act(async () => {
      await result.current.mutateAsync();
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/paper/refresh",
      expect.objectContaining({ method: "POST" }),
    );
    expect(spy).toHaveBeenCalledWith({ queryKey: ["blotter"] });
  });
});
