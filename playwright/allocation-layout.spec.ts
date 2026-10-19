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

test.beforeEach(async ({ page }) => {
  const credentials = getRoleCredentials(resolveRole("GUDANG"), loadLocalConfig());
  await page.goto("/login/");
  await page.locator("#id_username").fill(credentials.username);
  await page.locator("#id_password").fill(credentials.password);
  await page.locator('button[type="submit"]').click();
  await page.goto("/allocation/create/");
  await expect(page.locator("#allocation-form")).toBeVisible();
});

test("batch picker stays within the viewport and above Step 2 navigation", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const stockItemId = await page.locator("#allocation-stock-catalog").evaluate((element) => {
    const counts = new Map<number, number>();
    for (const stock of JSON.parse(element.textContent || "[]")) {
      counts.set(stock.itemId, (counts.get(stock.itemId) || 0) + 1);
    }
    return [...counts].find(([, count]) => count >= 2)?.[0];
  });
  expect(stockItemId, "The local database needs one item with two available batches").toBeTruthy();

  await page.locator('.wizard-step-btn[data-step="2"]').click();
  const row = page.locator('#step-2 .formset-row:not(.d-none)').first();
  const itemLabel = await row.locator(".js-item-select").evaluate((select, id) => {
    return (select as HTMLSelectElement).querySelector(`option[value="${id}"]`)?.textContent || "";
  }, stockItemId);
  await row.locator(".typeahead-input").fill(itemLabel);
  await page.locator(`.typeahead-dropdown.show .typeahead-item[data-value="${stockItemId}"]`).click();
  await row.locator(".js-batch-picker-toggle").click();
  const panel = row.locator(".js-batch-picker-panel");
  await expect(panel).toBeVisible();
  expect(await panel.locator(".js-batch-checkbox").count()).toBeGreaterThanOrEqual(2);

  const geometry = await page.evaluate(() => {
    const panel = document.querySelector("#step-2 .js-batch-picker-panel:popover-open")!;
    const nav = document.querySelector("#step-2 .js-step-2-nav")!;
    const bounds = panel.getBoundingClientRect();
    const navBounds = nav.getBoundingClientRect();
    return {
      top: bounds.top,
      bottom: bounds.bottom,
      left: bounds.left,
      right: bounds.right,
      navTop: navBounds.top,
      navBottom: navBounds.bottom,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    };
  });
  expect(geometry.top).toBeGreaterThanOrEqual(0);
  expect(geometry.bottom).toBeLessThanOrEqual(geometry.viewportHeight);
  expect(geometry.left).toBeGreaterThanOrEqual(0);
  expect(geometry.right).toBeLessThanOrEqual(geometry.viewportWidth);
  expect(geometry.bottom <= geometry.navTop || geometry.top >= geometry.navBottom).toBeTruthy();

  await panel.locator(".js-batch-checkbox").first().check();
  await panel.locator(".js-batch-checkbox").last().check();
  await expect(row.locator(".js-batch-picker-summary")).toHaveText("2 batch dipilih");
  await page.locator('.wizard-step-btn[data-step="2"]').click();
  await expect(panel).toBeHidden();

  for (let index = 0; index < 6; index++) {
    await page.locator('#step-2 .formset-add[data-formset-target="allocation-items"]').click();
  }
  await page.setViewportSize({ width: 600, height: 700 });
  const lastRow = page.locator('#step-2 .formset-row:not(.d-none)').last();
  await lastRow.locator(".typeahead-input").fill(itemLabel);
  await page.locator(`.typeahead-dropdown.show .typeahead-item[data-value="${stockItemId}"]`).click();
  await lastRow.locator(".js-batch-picker-toggle").scrollIntoViewIfNeeded();
  await lastRow.locator(".js-batch-picker-toggle").click();
  const lastPanel = lastRow.locator(".js-batch-picker-panel");
  await expect(lastPanel).toBeVisible();
  const lastGeometry = await lastPanel.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const visiblePoint = document.elementFromPoint(rect.left + 15, rect.top + 15);
    return {
      top: rect.top,
      bottom: rect.bottom,
      left: rect.left,
      right: rect.right,
      hitPanel: visiblePoint === element || element.contains(visiblePoint),
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    };
  });
  expect(lastGeometry.top).toBeGreaterThanOrEqual(0);
  expect(lastGeometry.bottom).toBeLessThanOrEqual(lastGeometry.viewportHeight);
  expect(lastGeometry.left).toBeGreaterThanOrEqual(0);
  expect(lastGeometry.right).toBeLessThanOrEqual(lastGeometry.viewportWidth);
  expect(lastGeometry.hitPanel).toBeTruthy();
  await page.screenshot({ path: path.join(os.tmpdir(), "allocation-batch-picker-narrow.png") });
  await expect(lastPanel.locator(".js-batch-checkbox").last()).toBeVisible();
  await lastPanel.locator(".js-batch-checkbox").last().check();
  await expect(lastRow.locator(".js-batch-picker-summary")).toContainText("Tersedia:");
  expect(pageErrors).toEqual([]);
});

test("removing a row closes its open batch picker", async ({ page }) => {
  const stockItemId = await page.locator("#allocation-stock-catalog").evaluate((element) => {
    return JSON.parse(element.textContent || "[]")[0]?.itemId;
  });
  expect(stockItemId).toBeTruthy();

  await page.locator('.wizard-step-btn[data-step="2"]').click();
  await page.locator('#step-2 .formset-add[data-formset-target="allocation-items"]').click();
  const firstRow = page.locator("#step-2 .formset-row").first();
  const itemLabel = await firstRow.locator(".js-item-select").evaluate((select, id) => {
    return (select as HTMLSelectElement).querySelector(`option[value="${id}"]`)?.textContent || "";
  }, stockItemId);
  await firstRow.locator(".typeahead-input").fill(itemLabel);
  await page.locator(`.typeahead-dropdown.show .typeahead-item[data-value="${stockItemId}"]`).click();
  await firstRow.locator(".js-batch-picker-toggle").click();
  const panel = firstRow.locator(".js-batch-picker-panel");
  await expect(panel).toBeVisible();

  await firstRow.locator(".formset-remove").click();
  await expect(firstRow).toHaveClass(/d-none/);
  await expect(panel).toBeHidden();
  expect(await panel.evaluate((element) => element.matches(":popover-open"))).toBe(false);
  await expect(firstRow.locator(".js-batch-picker-toggle")).toHaveAttribute("aria-expanded", "false");

  const remainingRow = page.locator("#step-2 .formset-row:not(.d-none)").first();
  await remainingRow.locator(".typeahead-input").fill(itemLabel);
  await page.locator(`.typeahead-dropdown.show .typeahead-item[data-value="${stockItemId}"]`).click();
  await remainingRow.locator(".js-batch-picker-toggle").click();
  await expect(remainingRow.locator(".js-batch-picker-panel")).toBeVisible();
});

test("Step 3 and Step 4 retain row and facility labels while scrolling both axes", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.setViewportSize({ width: 700, height: 700 });
  await page.locator('#allocation-facility-list input[type="checkbox"]').evaluateAll((boxes) => {
    boxes.forEach((box) => {
      (box as HTMLInputElement).checked = true;
      box.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
  const stockItemId = await page.locator("#allocation-stock-catalog").evaluate((element) => {
    return JSON.parse(element.textContent || "[]")[0]?.itemId;
  });
  expect(stockItemId).toBeTruthy();
  await page.locator('.wizard-step-btn[data-step="2"]').click();
  const row = page.locator('#step-2 .formset-row:not(.d-none)').first();
  const itemLabel = await row.locator(".js-item-select").evaluate((select, id) => {
    return (select as HTMLSelectElement).querySelector(`option[value="${id}"]`)?.textContent || "";
  }, stockItemId);
  await row.locator(".typeahead-input").fill(itemLabel);
  await page.locator(`.typeahead-dropdown.show .typeahead-item[data-value="${stockItemId}"]`).click();
  await row.locator(".js-batch-picker-toggle").click();
  await row.locator(".js-batch-checkbox").first().check();
  await page.locator('.wizard-step-btn[data-step="3"]').click();

  for (const step of [3, 4]) {
    if (step === 4) await page.locator('.wizard-step-btn[data-step="4"]').click();
    const wrapper = page.locator(`#step-${step} .alloc-matrix-scroll`);
    await expect(wrapper).toBeVisible();
    await wrapper.evaluate((element) => {
      const body = element.querySelector("tbody")!;
      while (body.children.length < 24) body.appendChild(body.firstElementChild!.cloneNode(true));
      element.scrollTop = element.scrollHeight;
      element.scrollLeft = element.scrollWidth;
    });
    const positions = await wrapper.evaluate((element) => {
      const wrap = element.getBoundingClientRect();
      const header = element.querySelector("thead th:nth-child(3)")!.getBoundingClientRect();
      const first = element.querySelector("tbody tr:last-child td:first-child")!.getBoundingClientRect();
      const corner = element.querySelector("thead th:first-child")!.getBoundingClientRect();
      const cornerStyle = getComputedStyle(element.querySelector("thead th:first-child")!);
      const headerStyle = getComputedStyle(element.querySelector("thead th:nth-child(3)")!);
      const firstStyle = getComputedStyle(element.querySelector("tbody tr:last-child td:first-child")!);
      return {
        scrollTop: element.scrollTop,
        scrollLeft: element.scrollLeft,
        headerTop: header.top,
        firstLeft: first.left,
        cornerTop: corner.top,
        cornerLeft: corner.left,
        wrapperTop: wrap.top,
        wrapperLeft: wrap.left,
        cornerZ: Number(cornerStyle.zIndex),
        headerZ: Number(headerStyle.zIndex),
        firstZ: Number(firstStyle.zIndex),
        backgrounds: [cornerStyle.backgroundColor, headerStyle.backgroundColor, firstStyle.backgroundColor],
      };
    });
    expect(positions.scrollTop).toBeGreaterThan(0);
    expect(positions.scrollLeft).toBeGreaterThan(0);
    expect(Math.abs(positions.headerTop - positions.wrapperTop)).toBeLessThan(3);
    expect(Math.abs(positions.firstLeft - positions.wrapperLeft)).toBeLessThan(3);
    expect(Math.abs(positions.cornerTop - positions.wrapperTop)).toBeLessThan(3);
    expect(Math.abs(positions.cornerLeft - positions.wrapperLeft)).toBeLessThan(3);
    expect(positions.cornerZ).toBeGreaterThan(positions.headerZ);
    expect(positions.headerZ).toBeGreaterThan(positions.firstZ);
    expect(positions.backgrounds.every((color) => color.startsWith("rgb("))).toBeTruthy();
    if (step === 3) {
      const lastInput = wrapper.locator("tbody tr:last-child .js-matrix-qty").last();
      await lastInput.fill("4");
      await expect(lastInput).toHaveValue("4");
    }
    await page.screenshot({ path: path.join(os.tmpdir(), `allocation-matrix-step-${step}.png`) });
  }
  expect(pageErrors).toEqual([]);
});
