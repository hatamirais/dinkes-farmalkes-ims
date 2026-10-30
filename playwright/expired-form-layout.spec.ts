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

test("Expired create preserves its item formset and narrow table scrolling", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/expired/create/");
    const form = page.locator('form[data-item-table-target="expired-items"]');
    await expect(form).toBeVisible();
    await expect(page.locator("#id_report_date")).toBeVisible();
    const notes = page.locator("#id_notes");
    const notesStyle = await notes.evaluate((element) => ({
      height: element.getBoundingClientRect().height,
      resize: getComputedStyle(element).resize,
    }));
    expect(notesStyle.height).toBeLessThanOrEqual(42);
    expect(notesStyle.resize).toBe("vertical");
    await notes.fill("Baris pertama\nBaris kedua");
    await expect(notes).toHaveValue("Baris pertama\nBaris kedua");
    await expect(form.locator('input[name="csrfmiddlewaretoken"]')).toHaveCount(1);
    await expect(form.locator('input[name="items-TOTAL_FORMS"]')).toHaveCount(1);
    const styles = await page.evaluate(() => ({
      tailwind: !!document.querySelector('link[href*="app.tailwind.css"]'),
      bootstrap: !!document.querySelector('link[href*="bootstrap.min.css"]'),
      overflow: document.documentElement.scrollWidth > innerWidth,
    }));
    expect(styles).toEqual({ tailwind: true, bootstrap: false, overflow: false });
    const table = page.locator('[data-formset="expired-items"]');
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
    await form.locator('button[type="submit"]').click();
    await expect(row.locator(".js-item-picker-field-error")).toBeVisible();
    await expect(row.locator('input[name$="-quantity"]')).toHaveClass(/item-picker-input-error/);
    await expect(row.locator('input[name$="-quantity"]')).toHaveCSS("border-color", "rgb(180, 35, 42)");
    await row.locator('input[name$="-quantity"]').fill("1");
    await expect(row.locator(".js-item-picker-field-error")).toBeHidden();
    await page.locator('[data-formset-target="expired-items"].formset-add').click();
    await expect(table.locator(".formset-row")).toHaveCount(2);
    await table.locator(".formset-row").last().locator(".formset-remove").click();
    await expect(table.locator(".formset-row").last()).toBeHidden();
  }
  expect(errors).toEqual([]);
});

test("selected stock query prefills the existing formset fields", async ({ page }) => {
  await page.goto("/expired/create/");
  const stockId = await page.locator("#expired-items-empty").evaluate((template) => {
    const select = (template as HTMLTemplateElement).content.querySelector(".js-stock-select") as HTMLSelectElement;
    return [...select.options].find((entry) => entry.value)?.value || "";
  });
  expect(stockId, "The local database needs an available dated stock row").not.toBe("");
  await page.goto(`/expired/create/?stocks=${encodeURIComponent(stockId)}`);
  const row = page.locator('[data-formset="expired-items"] .formset-row').first();
  await expect(row.locator(".js-stock-select")).toHaveValue(stockId);
  await expect(row.locator(".js-item-select")).not.toHaveValue("");
  const quantity = await row.locator('input[name$="-quantity"]').inputValue();
  expect(Number(quantity)).toBeGreaterThan(0);
});

test("an unmigrated workflow form retains Bootstrap CSS", async ({ page }) => {
  await page.goto("/stock-opname/create/");
  const styles = await page.evaluate(() => ({
    tailwind: !!document.querySelector('link[href*="app.tailwind.css"]'),
    bootstrap: !!document.querySelector('link[href*="bootstrap.min.css"]'),
  }));
  expect(styles).toEqual({ tailwind: false, bootstrap: true });
});
