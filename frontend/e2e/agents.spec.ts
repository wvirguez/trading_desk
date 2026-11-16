import { expect, test } from "@playwright/test";
import { installRestMocks } from "./support/mock-rest";
import { installStreamMock } from "./support/mock-ws";

const STEPS = ["STRUCTURE", "QUANT", "PROPOSAL", "GUARDS", "RISK_AUDIT"] as const;

test.describe("feed de razonamiento de agentes", () => {
  test("el análisis con SSE simulado muestra los cinco pasos y el resultado", async ({
    page,
  }) => {
    await installRestMocks(page, { analyze: "success" });
    await installStreamMock(page);
    await page.goto("/agents");

    await page.getByRole("button", { name: "Analizar" }).click();

    for (const step of STEPS) {
      await expect(
        page.locator(`[data-testid="step-card"][data-step="${step}"]`),
      ).toHaveAttribute("data-status", "completed", { timeout: 10_000 });
    }

    await expect(page.getByText("SIGNAL_APPROVED", { exact: true })).toBeVisible();
    await expect(page.getByText("Señal aprobada")).toBeVisible();
    await expect(page.getByText("Texto del modelo, no verificado").first()).toBeVisible();
  });

  test("un 503 simulado muestra el mensaje del backend y deja el formulario usable", async ({
    page,
  }) => {
    await installRestMocks(page, { analyze: "unavailable" });
    await installStreamMock(page);
    await page.goto("/agents");

    await page.getByRole("button", { name: "Analizar" }).click();

    await expect(
      page
        .getByText(
          "El análisis con agentes no está configurado: falta ANTHROPIC_API_KEY.",
        )
        .first(),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Analizar" })).toBeEnabled();
  });
});