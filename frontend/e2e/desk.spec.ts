import { expect, test } from "@playwright/test";
import { installRestMocks } from "./support/mock-rest";
import { installStreamMock } from "./support/mock-ws";

test.describe("terminal de lectura", () => {
  test("muestra velas, selectores y overlays, y recarga al cambiar símbolo y timeframe", async ({
    page,
  }) => {
    await installRestMocks(page, { analyze: "success" });
    await installStreamMock(page);
    await page.goto("/desk");

    await expect(page.getByTestId("last-price")).toHaveText("67250.00");
    await expect(page.locator("canvas").first()).toBeVisible();

    const overlays = page.getByTestId("chart-overlays-status");
    await expect(overlays).toHaveAttribute("data-signal-count", "1");
    await expect(overlays).toHaveAttribute("data-fvg-count", "2");
    await expect(overlays).toHaveAttribute("data-signals-visible", "true");
    await expect(overlays).toHaveAttribute("data-fvgs-visible", "true");

    await expect(page.getByText("Entrada:", { exact: true })).toBeVisible();
    await expect(page.getByText("67250.00", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Texto del modelo, no verificado")).toBeVisible();

    await page.getByRole("checkbox", { name: "Señales" }).uncheck();
    await expect(overlays).toHaveAttribute("data-signals-visible", "false");
    await page.getByRole("checkbox", { name: "Señales" }).check();

    await page.getByRole("checkbox", { name: "FVG" }).uncheck();
    await expect(overlays).toHaveAttribute("data-fvgs-visible", "false");
    await page.getByRole("checkbox", { name: "FVG" }).check();

    await page.getByRole("combobox").first().click();
    await page.getByRole("option", { name: "EUR/USD" }).click();
    await expect(page.getByTestId("last-price")).toHaveText("1.09620");
    await expect(overlays).toHaveAttribute("data-signal-count", "0");

    const ohlcvRequest = page.waitForRequest(
      (request) =>
        request.url().includes("/api/v1/market/ohlcv") &&
        request.url().includes("symbol=EUR%2FUSD") &&
        request.url().includes("tf=4h"),
    );
    await page.getByRole("combobox").nth(1).click();
    await page.getByRole("option", { name: "4h" }).click();
    await ohlcvRequest;

    await expect(page.getByTestId("last-price")).toHaveText("1.09840");
  });

  test("un tick y una alerta de señal del WebSocket simulado actualizan el terminal", async ({
    page,
  }) => {
    await installRestMocks(page, { analyze: "success" });
    await installStreamMock(page, { tick: true, signal: true, delayMs: 900 });
    await page.goto("/desk");

    await expect(page.getByTestId("last-price")).toHaveText("67250.00");
    await expect(page.getByTestId("last-price")).toHaveText("68000.50", {
      timeout: 10_000,
    });
    await expect(page.getByTestId("provisional-warning")).toBeVisible();
    await expect(page.getByTestId("signal-alert")).toHaveText(
      "Nueva señal aprobada recibida: BTC/USDT LONG",
    );
  });

  test("la navegación llega a las páginas marcadoras", async ({ page }) => {
    await installRestMocks(page, { analyze: "success" });
    await installStreamMock(page);
    await page.goto("/agents");

    await page.getByRole("link", { name: "Backtest" }).click();
    await expect(page).toHaveURL(/\/backtest$/);
    await expect(
      page.getByRole("main").getByText("Pendiente: paso 4.8"),
    ).toBeVisible();

    await page.getByRole("link", { name: "Diario" }).click();
    await expect(page).toHaveURL(/\/journal$/);
    await expect(
      page.getByRole("main").getByText("Pendiente: paso 4.9"),
    ).toBeVisible();
  });
});