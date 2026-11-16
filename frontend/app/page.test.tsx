import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
}));

describe("Home page", () => {
  it("redirige a /desk", async () => {
    const { redirect } = await import("next/navigation");
    const mod = await import("./page");
    const Home = mod.default as () => null;
    render(<Home />);
    expect(redirect).toHaveBeenCalledWith("/desk");
  });
});