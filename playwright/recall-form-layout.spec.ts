import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "playwright/test";
import { getRoleCredentials, loadLocalConfig, resolveRole } from "../scripts/playwright/common.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
test.use({ headless: true });
test.skip(!fs.existsSync(path.join(repoRoot, ".env.playwright.local")), "Requires local Playwright account configuration.");

test.beforeEach(async ({ page }) => {
  const credentials = getRoleCredentials(resolveRole("ADMIN"), loadLocalConfig());
  await page.goto("/login/");
  await page.locator("#id_username").fill(credentials.username);
  await page.locator("#id_password").fill(credentials.password);
  await page.locator('button[type="submit"]').click();
});

test("Recall create keeps its formset, validation, and contained table scrolling", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/recall/create/");
    await expect(page.locator("form[data-recall-form]")).toBeVisible();
    await expect(page.locator("#id_recall_date")).toBeVisible();
    await expect(page.locator("#id_supplier")).toBeVisible();
    await expect(page.locator("#id_notes")).toBeVisible();
    const notes = page.locator("#id_notes");
    const notesStyle = await notes.evaluate((element) => ({
      height: element.getBoundingClientRect().height,
      resize: getComputedStyle(element).resize,
    }));
    expect(notesStyle.height).toBeLessThanOrEqual(42);
    expect(notesStyle.resize).toBe("vertical");
    await notes.fill("Baris pertama\nBaris kedua");
    await expect(notes).toHaveValue("Baris pertama\nBaris kedua");
    await expect(page.locator('form[data-recall-form] input[name="csrfmiddlewaretoken"]')).toHaveCount(1);
    await expect(page.locator('form[data-recall-form] input[name="items-TOTAL_FORMS"]')).toHaveCount(1);
    const styles = await page.evaluate(() => ({
      tailwind: !!document.querySelector('link[href*="app.tailwind.css"]'),
      bootstrap: !!document.querySelector('link[href*="bootstrap.min.css"]'),
      overflow: document.documentElement.scrollWidth > innerWidth,
    }));
    expect(styles).toEqual({ tailwind: true, bootstrap: false, overflow: false });
    const table = page.locator('[data-formset="recall-items"]');
    if (width === 390) {
      expect(await table.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
    }

    const row = table.locator(".formset-row").first();
    const option = await row.locator(".js-item-select").evaluate((select) => {
      const first = [...(select as HTMLSelectElement).options].find((entry) => entry.value);
      return first ? { value: first.value, label: first.textContent || "" } : null;
    });
    expect(option, "The local catalog needs at least one item").not.toBeNull();
    await row.locator(".typeahead-input").fill(option!.label);
    await page.locator(`.typeahead-dropdown.show .typeahead-item[data-value="${option!.value}"]`).click();
    await expect(row.locator('input[name$="-quantity"]')).toBeEnabled();
    await expect(row.locator(".js-stock-select")).toBeEnabled();
    await page.locator('form[data-recall-form] button[type="submit"]').click();
    await expect(row.locator(".js-recall-quantity-error")).toBeVisible();
    await expect(row.locator('input[name$="-quantity"]')).toBeFocused();
    await row.locator('input[name$="-quantity"]').fill("1");
    await expect(row.locator(".js-recall-quantity-error")).toBeHidden();

    await page.locator('[data-formset-target="recall-items"].formset-add').click();
    await expect(table.locator(".formset-row")).toHaveCount(2);
    await table.locator(".formset-row").last().locator(".formset-remove").click();
    await expect(table.locator(".formset-row").last()).toBeHidden();
    page.once("dialog", (dialog) => dialog.accept());
    await page.locator('[data-formset-target="recall-items"].formset-clear').click();
    await expect(table.locator(".formset-row:visible")).toHaveCount(1);
    await expect(row.locator(".js-item-select")).toHaveValue("");
    await page.locator('form[data-recall-form] button[type="submit"]').click();
    await expect(page.locator(".js-recall-table-error")).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test("an unmigrated workflow form keeps Bootstrap CSS", async ({ page }) => {
  await page.goto("/expired/create/");
  await expect(page.locator('form[data-item-picker-table]')).toBeVisible();
  const styles = await page.evaluate(() => ({
    tailwind: !!document.querySelector('link[href*="app.tailwind.css"]'),
    bootstrap: !!document.querySelector('link[href*="bootstrap.min.css"]'),
  }));
  expect(styles).toEqual({ tailwind: false, bootstrap: true });
});
