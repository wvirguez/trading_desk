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

  it("ya no muestra ningún badge «Pendiente»", () => {
    for (const route of routes) {
      usePathnameMock.mockReturnValue(route.path);
      const { unmount } = render(<Sidebar />);
      expect(screen.queryByText(/Pendiente/)).not.toBeInTheDocument();
      unmount();
    }
  });
});
