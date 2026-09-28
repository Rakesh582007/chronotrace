import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const USER = process.env.DEMO_DOCTOR_USER ?? "demo.doctor";
const PASSWORD = process.env.DEMO_DOCTOR_PASSWORD ?? "chronotrace";
const R10 = process.env.R10_PDF ?? path.resolve(__dirname, "../../backend/demo/generated/selvam_R10_2026-03-02.pdf");
const SHOTS = path.resolve(__dirname, "../screenshots");

test("demo path: login → patients → Selvam → Kidney → eGFR → Medications → upload R10 → KDIGO → Summary", async ({ page }) => {
  await page.goto("/login");
  await page.fill("#username", USER);
  await page.fill("#password", PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "My patients" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${SHOTS}/1-patients.png` });

  await page.getByRole("link", { name: /K\. Selvam/ }).click();
  await expect(page.getByRole("heading", { name: "Needs your review" })).toBeVisible();
  await expect(page.getByTestId("guideline-card")).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${SHOTS}/2-trends-before.png` });

  await page.getByTestId("system-kidney").click();
  await expect(page.getByRole("heading", { name: "Kidney" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${SHOTS}/3-kidney.png` });

  await page.getByRole("link", { name: "Open eGFR →" }).first().click();
  await expect(page.getByRole("heading", { name: "Results" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${SHOTS}/4-egfr.png` });

  await page.getByRole("link", { name: "Medications", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Medications and lab response" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${SHOTS}/5-medications.png` });

  await page.getByRole("link", { name: "Add documents" }).click();
  await page.getByTestId("lab-input").setInputFiles(R10);
  await expect(page.getByText("Check the extracted values")).toBeVisible({ timeout: 60_000 });
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${SHOTS}/6-review.png` });
  await page.getByTestId("confirm-report").click();

  const card = page.getByTestId("guideline-card");
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card).toContainText("KDIGO");
  await expect(card).not.toContainText(/rapid/i);
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${SHOTS}/7-trends-after.png` });

  await page.getByRole("link", { name: "Summary", exact: true }).first().click();
  await expect(page.getByText("Whole history")).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${SHOTS}/8-summary.png` });
});
