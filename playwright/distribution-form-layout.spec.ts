import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "playwright/test";
import { getRoleCredentials, loadLocalConfig, resolveRole } from "../scripts/playwright/common.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
test.use({ headless: true });
test.skip(!fs.existsSync(path.join(repoRoot, ".env.playwright.local")), "Requires local Playwright account configuration.");

test.beforeEach(async ({ page }) => {
  const credentials = getRoleCredentials(resolveRole("GUDANG"), loadLocalConfig());
  await page.goto("/login/");
  await page.locator("#id_username").fill(credentials.username);
  await page.locator("#id_password").fill(credentials.password);
  await page.locator('button[type="submit"]').click();
});

test("distribution create variants keep their form controls and internal table scrolling", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const route of ["/distribution/create/", "/distribution/special-requests/create/", "/distribution/lplpo/create/"]) {
    for (const width of [1440, 900, 768, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(route);
      await expect(page.locator("#distribution-form-container")).toBeVisible();
      await expect(page.locator('#distribution-form-container input[name="csrfmiddlewaretoken"]')).toHaveCount(1);
      await expect(page.locator('#distribution-form-container input[name="items-TOTAL_FORMS"]')).toHaveCount(1);
      await expect(page.locator("#id_facility")).toBeVisible();
      const notes = page.locator("#id_notes");
      const notesStyle = await notes.evaluate((element) => ({
        height: element.getBoundingClientRect().height,
        resize: getComputedStyle(element).resize,
      }));
      expect(notesStyle.height, `${route} at ${width}px notes height`).toBeLessThanOrEqual(42);
      expect(notesStyle.resize).toBe("vertical");
      await notes.fill("Baris pertama\nBaris kedua");
      await expect(notes).toHaveValue("Baris pertama\nBaris kedua");
      if (width >= 768) {
        const fieldTops = await page.evaluate(() => ({
          date: document.querySelector("#id_request_date")!.getBoundingClientRect().top,
          facility: document.querySelector("#id_facility")!.getBoundingClientRect().top,
        }));
        expect(Math.abs(fieldTops.date - fieldTops.facility), `${route} field alignment`).toBeLessThanOrEqual(1);
      }
      const styles = await page.evaluate(() => ({
        tailwind: !!document.querySelector('link[href*="app.tailwind.css"]'),
        bootstrap: !!document.querySelector('link[href*="bootstrap.min.css"]'),
        overflow: document.documentElement.scrollWidth > innerWidth,
      }));
      expect(styles, `${route} at ${width}px`).toEqual({ tailwind: true, bootstrap: false, overflow: false });
      const table = page.locator('[data-formset="distribution-items"]');
      if (width === 390) {
        expect(await table.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
      } else if (width === 1440) {
        expect(await table.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      }
      await page.locator('[data-formset-target="distribution-items"].formset-add').click();
      await expect(table.locator(".formset-row")).toHaveCount(4);
      await page.locator('[data-bs-target="#distribution-staff-picker-body"]').click();
      await expect(page.locator("#distribution-staff-picker-body")).toBeVisible();
      await page.locator(".js-staff-filter").fill("no matching staff 8d5c4f1a");
      await expect(page.locator(".staff-picker-item:visible")).toHaveCount(0);
      await expect(page.locator(".staff-picker-empty")).toBeVisible();
      await page.locator('[data-bs-target="#modal-facility"]').click();
      await expect(page.locator("#modal-facility")).toBeVisible();
      await page.locator('#modal-facility [data-bs-dismiss="modal"]').first().click();
      await expect(page.locator("#modal-facility")).toBeHidden();
    }
  }
  expect(errors).toEqual([]);
});
