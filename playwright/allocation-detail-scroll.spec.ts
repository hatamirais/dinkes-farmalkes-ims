import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "playwright/test";
import { getRoleCredentials, loadLocalConfig, resolveRole } from "../scripts/playwright/common.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const hasLocalAccount = fs.existsSync(path.join(repoRoot, ".env.playwright.local"));

test.use({ headless: true });
test.skip(!hasLocalAccount, "Requires the repository's local Playwright account configuration.");

test("allocation distribution fragments return middle and last cards to view", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const credentials = getRoleCredentials(resolveRole("GUDANG"), loadLocalConfig());
  await page.goto("/login/");
  await page.locator("#id_username").fill(credentials.username);
  await page.locator("#id_password").fill(credentials.password);
  await page.locator('button[type="submit"]').click();
  await page.goto("/allocation/");

  const detailPath = await page.locator(".table tbody tr").evaluateAll((rows) => {
    const candidate = rows.find((row) => {
      const facilityCount = Number.parseInt(row.querySelectorAll("td")[2]?.textContent || "", 10);
      return facilityCount >= 6;
    });
    return candidate?.querySelector<HTMLAnchorElement>('a[href^="/allocation/"]')?.getAttribute("href") || "";
  });
  test.skip(!detailPath, "Requires a local allocation with at least six facilities.");

  await page.goto(detailPath);
  const cards = page.locator(".dist-tracking-anchor");
  const count = await cards.count();
  test.skip(count < 6, "The selected allocation does not have six generated distributions.");

  for (const index of [Math.floor(count / 2), count - 1]) {
    const cardId = await cards.nth(index).getAttribute("id");
    expect(cardId).toMatch(/^distribution-\d+$/);
    await page.goto(`${detailPath}#${cardId}`);
    await expect(page).toHaveURL(new RegExp(`#${cardId}$`));
    await expect(page.locator(`#${cardId}`)).toBeInViewport({ ratio: 0.5 });
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  }

  await page.screenshot({ path: path.join(os.tmpdir(), "allocation-detail-card-anchor.png") });
  expect(pageErrors).toEqual([]);
});
