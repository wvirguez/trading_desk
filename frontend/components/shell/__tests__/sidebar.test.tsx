import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const usePathnameMock = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => usePathnameMock(),
}));

import Sidebar from "@/components/shell/sidebar";

describe("Sidebar", () => {
  const routes = [
    { path: "/desk", label: "Desk" },
    { path: "/backtest", label: "Backtest" },
    { path: "/agents", label: "Agentes" },
    { path: "/journal", label: "Diario" },
  ];

  beforeEach(() => {
    usePathnameMock.mockReset();
  });

  it("muestra los cuatro enlaces de navegación", () => {
    usePathnameMock.mockReturnValue("/desk");

    render(<Sidebar />);

    for (const route of routes) {
      const link = screen.getByRole("link", { name: route.label });
      expect(link).toHaveAttribute("href", route.path);
    }
  });

  it("marca el enlace activo", () => {
    usePathnameMock.mockReturnValue("/agents");

    render(<Sidebar />);

    const activeLabel = screen.getByText("Agentes");
    expect(activeLabel).toHaveAttribute("aria-current", "page");
  });

  it("muestra 'Pendiente: paso 4.8' en /backtest", () => {
    usePathnameMock.mockReturnValue("/backtest");

    render(<Sidebar />);
    expect(screen.getByText("Pendiente: paso 4.8")).toBeInTheDocument();
  });

  it("muestra 'Pendiente: paso 4.9' en /journal", () => {
    usePathnameMock.mockReturnValue("/journal");

    render(<Sidebar />);
    expect(screen.getByText("Pendiente: paso 4.9")).toBeInTheDocument();
  });
});