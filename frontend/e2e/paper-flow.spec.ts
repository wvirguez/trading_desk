import { expect, test, type Page } from "@playwright/test";
import { installRestMocks } from "./support/mock-rest";
import { installStreamMock } from "./support/mock-ws";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000/api/v1";
const SIGNAL_ID = "11111111-1111-4111-8111-111111111111";

async function analyzeAndGoToDesk(page: Page): Promise<void> {
  await page.goto("/agents");
  await page.getByRole("button", { name: "Analizar" }).click();
  await expect(page.getByText("SIGNAL_APPROVED", { exact: true })).toBeVisible({
    timeout: 10_000,
  });
  await page.getByRole("link", { name: "Desk" }).click();
  await expect(page).toHaveURL(/\/desk$/);
}

test.describe("flujo completo de paper trading", () => {
  test("analizar, ejecutar, actualizar el blotter y ver la entrada en el diario", async ({
    page,
  }) => {
    await installRestMocks(page, { analyze: "success", initialSignals: "none" });
    await installStreamMock(page);

    await analyzeAndGoToDesk(page);

    const overlays = page.getByTestId("chart-overlays-status");
    await expect(overlays).toHaveAttribute("data-signal-count", "1", { timeout: 10_000 });
    await expect(overlays).toHaveAttribute("data-signals-visible", "true");
    // Las líneas de precio se dibujan en el canvas: el componente expone qué niveles pintó.
    await expect(page.getByTestId("chart-price-lines")).toHaveAttribute(
      "data-lines",
      "Entrada,SL,TP",
    );
    const signalsPanel = page.getByRole("tabpanel", { name: "Señales" });
    await expect(signalsPanel.getByText("Entrada:", { exact: true })).toBeVisible();
    await expect(signalsPanel.getByText("SL:", { exact: true })).toBeVisible();
    await expect(signalsPanel.getByText("TP:", { exact: true })).toBeVisible();
    await expect(signalsPanel.getByText("67250.00", { exact: true })).toBeVisible();
    await expect(signalsPanel.getByText("66800.00", { exact: true })).toBeVisible();
    await expect(signalsPanel.getByText("68150.00", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Ejecutar (paper)" }).click();
    await page.getByRole("button", { name: "Confirmar ejecución simulada" }).click();

    // La señal ejecutada sale de las activas.
    await expect(page.getByText("Sin señales activas para el símbolo seleccionado")).toBeVisible();

    await page.getByRole("tab", { name: "Blotter" }).click();
    const row = page.getByRole("row", { name: /BTC\/USDT/ });
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("PENDING_FILL");

    await page.getByRole("button", { name: "Actualizar" }).click();
    await expect(row).toContainText("CLOSED_TP");
    await expect(row).toContainText("68150.00");
    await expect(row).toContainText("90.00");
    await expect(row).toContainText("2.68");
    await expect(page.getByText("10090.00", { exact: true }).first()).toBeVisible();

    await page.getByRole("tab", { name: "Señales" }).click();
    await expect(page.getByText("Sin señales activas para el símbolo seleccionado")).toBeVisible();

    // El estado del mock persiste al navegar: el diario refleja la orden cerrada.
    await page.goto("/journal");
    const entry = page.getByRole("row", { name: /BTC\/USDT/ });
    await expect(entry).toHaveCount(1);
    await expect(entry).toContainText("EXECUTED");
    await expect(entry).toContainText("WIN");
    await expect(entry).toContainText("2.68");
  });

  test("ejecutar dos veces devuelve 409 visible y no duplica la orden", async ({ page }) => {
    await installRestMocks(page, { analyze: "success" });
    await installStreamMock(page);
    await page.goto("/desk");

    await expect(page.getByRole("button", { name: "Ejecutar (paper)" })).toBeVisible();

    // Otra pestaña ejecuta antes la misma señal: la lista local sigue desactualizada.
    const firstStatus = await page.evaluate(async ({ id, apiUrl }) => {
      const response = await fetch(`${apiUrl}/signals/${id}/execute`, {
        method: "POST",
      });
      return response.status;
    }, { id: SIGNAL_ID, apiUrl: API_URL });
    expect(firstStatus).toBe(200);

    await page.getByRole("button", { name: "Ejecutar (paper)" }).click();
    await page.getByRole("button", { name: "Confirmar ejecución simulada" }).click();

    await expect(
      page.getByRole("alert").filter({ hasText: `La señal ${SIGNAL_ID} ya fue ejecutada.` }),
    ).toBeVisible();

    // Tras el 409 la lista se reconcilia: la señal ejecutada ya no está activa.
    await page.getByRole("tab", { name: "Blotter" }).click();
    await expect(page.getByRole("row", { name: /BTC\/USDT/ })).toHaveCount(1);
    await page.getByRole("tab", { name: "Señales" }).click();
    await expect(page.getByRole("button", { name: "Ejecutar (paper)" })).toHaveCount(0, {
      timeout: 15_000,
    });
  });

  test("el veto por pérdida diaria muestra el motivo y la señal sigue aprobada", async ({
    page,
  }) => {
    await installRestMocks(page, { analyze: "success", dailyLossVeto: true });
    await installStreamMock(page);
    await page.goto("/desk");

    await page.getByRole("button", { name: "Ejecutar (paper)" }).click();
    await page.getByRole("button", { name: "Confirmar ejecución simulada" }).click();

    const veto = page.getByRole("alert").filter({ hasText: "pérdida diaria alcanzada" });
    await expect(veto).toBeVisible();
    await expect(veto).toContainText("DAILY_LOSS_LIMIT");
    await expect(page.getByText("APPROVED", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Ejecutar (paper)" })).toBeEnabled();

    await page.getByRole("tab", { name: "Blotter" }).click();
    await expect(
      page.getByText("Sin órdenes simuladas. Ejecuta una señal aprobada."),
    ).toBeVisible();
  });
});
