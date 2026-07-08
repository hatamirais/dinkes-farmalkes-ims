import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "playwright/test";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const allocationScriptPath = path.resolve(__dirname, "../backend/static/js/allocation-form.js");

const stockCatalog = [
  {
    id: 1001,
    itemId: 501,
    label: "0374MA032 | Tersedia: 160 | Exp: 07/01/2026",
    availableQty: 160,
  },
  {
    id: 1002,
    itemId: 501,
    label: "0374MA097 | Tersedia: 25 | Exp: 27/02/2027",
    availableQty: 25,
  },
  {
    id: 1003,
    itemId: 501,
    label: "UHEOE | Tersedia: 100 | Exp: 01/06/2030",
    availableQty: 100,
  },
  {
    id: 2001,
    itemId: 601,
    label: "401624 | Tersedia: 127 | Exp: 30/06/2027",
    availableQty: 127,
  },
  {
    id: 3001,
    itemId: 701,
    label: "21001025 | Tersedia: 255 | Exp: 28/07/2028",
    availableQty: 255,
  },
];

const existingAllocations = {
  "101_1": 10,
  "101_2": 10,
  "102_1": 5,
  "103_2": 7,
  "201_1": 10,
  "201_2": 10,
  "301_1": 10,
  "301_2": 10,
};

function buildItemOptions(selectedItemId: number) {
  return [
    { value: 501, label: "Vaksin BCG" },
    { value: 601, label: "Vaksin HPV" },
    { value: 701, label: "Vaksin polio ipv 0,5 ml (i.m.)" },
  ]
    .map((item) => `<option value="${item.value}" ${item.value === selectedItemId ? "selected" : ""}>${item.label}</option>`)
    .join("");
}

function buildStockOptions(selectedStockId: number) {
  return stockCatalog
    .map((stock) => `<option value="${stock.id}" ${stock.id === selectedStockId ? "selected" : ""}>${stock.label}</option>`)
    .join("");
}

function buildRowHtml({
  index,
  persistedId,
  itemId,
  stockId,
  availableText,
  summaryText,
  groupId,
  generated = false,
}: {
  index: number;
  persistedId: number;
  itemId: number;
  stockId: number;
  availableText: string;
  summaryText: string;
  groupId: string;
  generated?: boolean;
}) {
  const hiddenClass = generated ? " d-none" : "";
  const generatedAttrs = generated
    ? ` data-generated-batch-row="true" data-batch-group-id="${groupId}"`
    : ` data-batch-group-id="${groupId}"`;

  return `
    <tr class="formset-row${hiddenClass}"${generatedAttrs}>
      <td>
        <select class="js-item-select" name="items-${index}-item">
          <option value="">---------</option>
          ${buildItemOptions(itemId)}
        </select>
      </td>
      <td>
        <div class="allocation-item-stock-shell">
          <div class="allocation-item-stock-source">
            <select class="js-stock-select" name="items-${index}-stock">
              <option value="">---------</option>
              ${buildStockOptions(stockId)}
            </select>
          </div>
          <div class="batch-checkbox-picker js-batch-picker" data-empty-label="Pilih batch stok">
            <button type="button" class="batch-checkbox-trigger js-batch-picker-toggle">
              <span class="batch-checkbox-trigger-text js-batch-picker-summary">${summaryText}</span>
              <span class="batch-checkbox-trigger-icon">▾</span>
            </button>
            <div class="batch-checkbox-panel js-batch-picker-panel d-none">
              <div class="batch-checkbox-list js-batch-checkbox-list"></div>
              <div class="batch-checkbox-empty js-batch-checkbox-empty">Pilih barang terlebih dahulu.</div>
            </div>
          </div>
        </div>
      </td>
      <td class="js-available-qty">${availableText}</td>
      <td>
        <button type="button" class="formset-remove">Hapus</button>
        <input type="checkbox" name="items-${index}-DELETE">
      </td>
      <td class="d-none"><input type="hidden" name="items-${index}-total_qty_available" value="${availableText}"></td>
      <td class="d-none"><input type="hidden" name="items-${index}-id" value="${persistedId}"></td>
    </tr>
  `;
}

function buildHarnessHtml(allocationScript: string) {
  return `
    <!DOCTYPE html>
    <html lang="id">
      <body>
        <input id="id_title" value="Alokasi Uji Multi Batch">
        <input id="id_allocation_date" value="2026-07-08">
        <input id="id_referensi" value="REF-001">
        <textarea id="id_notes">Catatan uji</textarea>

        <div id="wizard-validation-alert" class="d-none"></div>

        <button type="button" class="wizard-step-btn active" data-step="1"></button>
        <button type="button" class="wizard-step-btn" data-step="2"></button>
        <button type="button" class="wizard-step-btn" data-step="3"></button>
        <button type="button" class="wizard-step-btn" data-step="4"></button>

        <div class="wizard-panel" id="step-1"></div>
        <div class="wizard-panel active" id="step-2">
          <div data-formset="allocation-items" data-formset-prefix="items">
            <input type="hidden" name="items-TOTAL_FORMS" value="5">
            <table><tbody>
              ${buildRowHtml({ index: 0, persistedId: 101, itemId: 501, stockId: 1001, availableText: "285", summaryText: "3 batch dipilih", groupId: "group-bcg" })}
              ${buildRowHtml({ index: 1, persistedId: 201, itemId: 601, stockId: 2001, availableText: "127", summaryText: "401624 | Tersedia: 127 | Exp: 30/06/2027", groupId: "group-hpv" })}
              ${buildRowHtml({ index: 2, persistedId: 301, itemId: 701, stockId: 3001, availableText: "255", summaryText: "21001025 | Tersedia: 255 | Exp: 28/07/2028", groupId: "group-polio" })}
              ${buildRowHtml({ index: 3, persistedId: 102, itemId: 501, stockId: 1002, availableText: "25", summaryText: "3 batch dipilih", groupId: "group-bcg", generated: true })}
              ${buildRowHtml({ index: 4, persistedId: 103, itemId: 501, stockId: 1003, availableText: "100", summaryText: "3 batch dipilih", groupId: "group-bcg", generated: true })}
            </tbody></table>
          </div>
          <button type="button" class="js-wizard-next" data-next-step="3">Step 3</button>
        </div>
        <div class="wizard-panel" id="step-3">
          <table>
            <thead>
              <tr id="matrix-header-row">
                <th>Barang (Batch)</th>
                <th>Stok Tersedia</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody id="matrix-body"></tbody>
          </table>
          <div id="matrix-empty-msg" class="d-none"></div>
          <button type="button" class="js-wizard-next" data-next-step="4">Step 4</button>
        </div>
        <div class="wizard-panel" id="step-4">
          <div id="review-header-content"></div>
          <div id="review-matrix-content"></div>
        </div>

        <div class="selection-picker-list" id="allocation-facility-list">
          <label class="selection-picker-item">
            <span class="form-check-label">Puskesmas Arut Selatan</span>
            <input type="checkbox" value="1" checked>
          </label>
          <label class="selection-picker-item">
            <span class="form-check-label">Puskesmas Arut Utara</span>
            <input type="checkbox" value="2" checked>
          </label>
          <div class="selection-picker-empty d-none"></div>
        </div>

        <div class="selection-picker-list" id="allocation-staff-list">
          <label class="selection-picker-item">
            <span class="form-check-label">Petugas Gudang</span>
            <input type="checkbox" value="11" checked>
          </label>
          <div class="selection-picker-empty d-none"></div>
        </div>

        <template id="allocation-items-empty"></template>

        <script id="allocation-stock-catalog" type="application/json">${JSON.stringify(stockCatalog)}</script>
        <script id="allocation-facility-picker-meta" type="application/json">{}</script>
        <script id="allocation-staff-picker-meta" type="application/json">{}</script>
        <script id="existing-allocations" type="application/json">${JSON.stringify(existingAllocations)}</script>
        <script>${allocationScript}</script>
      </body>
    </html>
  `;
}

test.use({ headless: true });

test("allocation wizard groups split batches with their source item in step 3 and step 4", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => {
    pageErrors.push(error.message);
  });

  const allocationScript = await fs.readFile(allocationScriptPath, "utf8");

  await page.setContent(buildHarnessHtml(allocationScript));
  await page.waitForTimeout(50);

  expect(pageErrors).toEqual([]);
  await expect(page.locator("#step-2 .js-available-qty").first()).toHaveText("285");

  await page.evaluate(() => {
    (window as typeof window & { __allocationWizardTestApi: { buildMatrix: () => void } }).__allocationWizardTestApi.buildMatrix();
  });

  const matrixRows = page.locator("#matrix-body tr");
  await expect(matrixRows).toHaveCount(5);
  await expect(page.locator("#matrix-body tr td:nth-child(2)")).toHaveText(["160", "25", "100", "127", "255"]);
  await expect(page.locator("#matrix-body tr td:first-child > div")).toHaveText([
    "Vaksin BCG",
    "Vaksin BCG",
    "Vaksin BCG",
    "Vaksin HPV",
    "Vaksin polio ipv 0,5 ml (i.m.)",
  ]);
  await expect(page.locator('input[name="alloc_101_1"]')).toHaveValue("10");
  await expect(page.locator('input[name="alloc_101_2"]')).toHaveValue("10");
  await expect(page.locator('input[name="alloc_102_1"]')).toHaveValue("5");
  await expect(page.locator('input[name="alloc_103_2"]')).toHaveValue("7");

  await page.evaluate(() => {
    (window as typeof window & { __allocationWizardTestApi: { buildReviewMatrix: () => void } }).__allocationWizardTestApi.buildReviewMatrix();
  });

  const reviewRows = page.locator("#review-matrix-content tbody tr");
  await expect(reviewRows).toHaveCount(5);
  await expect(page.locator("#review-matrix-content tbody tr td:nth-child(2)")).toHaveText(["160", "25", "100", "127", "255"]);
  await expect(page.locator("#review-matrix-content tbody tr td:first-child")).toContainText([
    "Vaksin BCG",
    "Vaksin BCG",
    "Vaksin BCG",
    "Vaksin HPV",
    "Vaksin polio ipv 0,5 ml (i.m.)",
  ]);
});
