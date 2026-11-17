import { expect, test } from "@playwright/test";
import { installRestMocks } from "./support/mock-rest";
import { installStreamMock } from "./support/mock-ws";

test.describe("backtest", () => {
  test("ejecutar con los valores por defecto muestra métricas y curva de capital", async ({
    page,
  }) => {
    await installRestMocks(page, { backtest: "success" });
    await installStreamMock(page);
    await page.goto("/backtest");

    await page.getByRole("button", { name: "Ejecutar backtest" }).click();

    const metrics = page.getByRole("region", { name: "Métricas del backtest" });
    await expect(metrics).toBeVisible();
    await expect(metrics.getByText("Retorno total")).toBeVisible();
    await expect(metrics.getByText("8.42 %")).toBeVisible();
    await expect(metrics.getByText("10842.00")).toBeVisible();
    await expect(metrics.getByText("El backtest no modela costes ni slippage")).toBeVisible();

    await expect(page.getByRole("heading", { name: "Curva de capital" })).toBeVisible();
    await expect(page.getByTestId("equity-chart")).toBeVisible();
    await expect(page.getByTestId("equity-chart").locator("canvas").first()).toBeVisible();
  });

  test("un 422 simulado muestra su mensaje y deja el formulario usable", async ({ page }) => {
    await installRestMocks(page, { backtest: "invalid" });
    await installStreamMock(page);
    await page.goto("/backtest");

    await page.getByRole("button", { name: "Ejecutar backtest" }).click();

    await expect(
      page.getByRole("alert").filter({ hasText: "la Z de entrada debe ser mayor que la Z de salida" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Ejecutar backtest" })).toBeEnabled();

    await page.getByLabel("Z de entrada").fill("3");
    await expect(page.getByLabel("Z de entrada")).toHaveValue("3");

    // Reenviar tras el 422 lanza una nueva petición (el formulario no queda bloqueado).
    const resubmit = page.waitForRequest(
      (request) => request.url().endsWith("/quant/backtest") && request.method() === "POST",
    );
    await page.getByRole("button", { name: "Ejecutar backtest" }).click();
    await resubmit;
  });
});
