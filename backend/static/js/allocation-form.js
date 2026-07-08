/**
 * Allocation Form — 4-step wizard with dynamic allocation matrix.
 *
 * Step 1: Info Umum (sumber_dana, referensi, facilities, staff)
 * Step 2: Item selection (formset with stock/batch selector)
 * Step 3: Facility allocation matrix (dynamic columns, real-time validation)
 * Step 4: Read-only review generated from form data
 */

function initAllocationForm() {
    const stockCatalog = JSON.parse(
        document.getElementById('allocation-stock-catalog')?.textContent || '[]'
    );
    const facilityPickerMeta = JSON.parse(
        document.getElementById('allocation-facility-picker-meta')?.textContent || '{}'
    );
    const staffPickerMeta = JSON.parse(
        document.getElementById('allocation-staff-picker-meta')?.textContent || '{}'
    );

    let existingAllocations = {};
    const existingEl = document.getElementById('existing-allocations');
    if (existingEl) {
        try { existingAllocations = JSON.parse(existingEl.textContent || '{}'); }
        catch { existingAllocations = {}; }
    }

    // ────────────────────────────────────
    // Wizard navigation
    // ────────────────────────────────────

    const stepBtns = document.querySelectorAll('.wizard-step-btn');
    const panels = document.querySelectorAll('.wizard-panel');
    const wizardValidationAlert = document.getElementById('wizard-validation-alert');

    function hideWizardAlert() {
        if (!wizardValidationAlert) return;
        wizardValidationAlert.classList.add('d-none');
        wizardValidationAlert.textContent = '';
    }

    function showWizardAlert(message) {
        if (!wizardValidationAlert) return;
        wizardValidationAlert.textContent = message;
        wizardValidationAlert.classList.remove('d-none');
        wizardValidationAlert.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    function getStepThreeReadiness() {
        const facilities = getSelectedFacilities();
        const items = getBatchMatrixItems();
        return {
            facilities,
            items,
            hasFacilities: facilities.length > 0,
            hasItems: items.length > 0,
        };
    }

    function getStepThreeMissingMessage(readiness) {
        if (!readiness.hasFacilities && !readiness.hasItems) {
            return 'Pilih minimal 1 fasilitas pada Step 1 dan minimal 1 item dengan batch pada Step 2 sebelum lanjut ke Step 3.';
        }
        if (!readiness.hasFacilities) {
            return 'Pilih minimal 1 fasilitas pada Step 1 sebelum lanjut ke Step 3.';
        }
        if (!readiness.hasItems) {
            return 'Pilih minimal 1 item dengan batch pada Step 2 sebelum lanjut ke Step 3.';
        }
        return '';
    }

    function canEnterStep(targetStep) {
        if (targetStep < 3) {
            hideWizardAlert();
            return true;
        }

        const readiness = getStepThreeReadiness();
        if (readiness.hasFacilities && readiness.hasItems) {
            hideWizardAlert();
            return true;
        }

        showWizardAlert(getStepThreeMissingMessage(readiness));
        return false;
    }

    function goToStep(n) {
        if (!canEnterStep(n)) return;

        stepBtns.forEach(btn => btn.classList.toggle('active', parseInt(btn.dataset.step) === n));
        panels.forEach(panel => panel.classList.toggle('active', panel.id === `step-${n}`));

        if (n === 3) buildMatrix();
        if (n === 4) buildReview();
    }

    stepBtns.forEach(btn => {
        btn.addEventListener('click', () => goToStep(parseInt(btn.dataset.step)));
    });

    document.querySelectorAll('.js-wizard-next').forEach(btn => {
        btn.addEventListener('click', () => goToStep(parseInt(btn.dataset.nextStep)));
    });

    document.querySelectorAll('.js-wizard-prev').forEach(btn => {
        btn.addEventListener('click', () => goToStep(parseInt(btn.dataset.prevStep)));
    });

    // ────────────────────────────────────
    // Stock catalog cascading (Step 2)
    // ────────────────────────────────────

    function handleItemChange(itemSelect) {
        const row = itemSelect.closest('tr');
        if (!row) return;
        const stockSelect = row.querySelector('.js-stock-select');
        if (!stockSelect) return;

        const selectedItemId = itemSelect.value;
        stockSelect.innerHTML = '<option value="">---------</option>';

        if (!selectedItemId) return;

        const matchingStocks = stockCatalog.filter(s => String(s.itemId) === String(selectedItemId));
        matchingStocks.forEach(stock => {
            const opt = document.createElement('option');
            opt.value = stock.id;
            opt.textContent = stock.label;
            opt.dataset.availableQty = stock.availableQty;
            stockSelect.appendChild(opt);
        });
    }

    function handleStockChange(stockSelect) {
        const row = stockSelect.closest('tr');
        if (!row) return;
        const qtyCell = row.querySelector('.js-available-qty');
        const hiddenQtyInput = row.querySelector('[name$="-total_qty_available"]');
        const selectedOption = stockSelect.options[stockSelect.selectedIndex];

        if (selectedOption && selectedOption.dataset.availableQty) {
            const qty = selectedOption.dataset.availableQty;
            if (qtyCell) qtyCell.textContent = qty;
            if (hiddenQtyInput) hiddenQtyInput.value = qty;
        } else {
            if (qtyCell) qtyCell.textContent = '—';
            if (hiddenQtyInput) hiddenQtyInput.value = '0';
        }
    }

    document.addEventListener('change', (e) => {
        if (e.target.matches('.js-item-select')) handleItemChange(e.target);
        if (e.target.matches('.js-stock-select')) handleStockChange(e.target);
    });

    let batchGroupCounter = 0;

    function getAllocationFormsetState() {
        const formsetContainer = document.querySelector('[data-formset="allocation-items"]');
        if (!formsetContainer) return null;

        const prefix = formsetContainer.dataset.formsetPrefix;
        const totalInput = document.querySelector(`input[name="${prefix}-TOTAL_FORMS"]`);
        const tableBody = formsetContainer.querySelector('tbody');
        const emptyTemplate = document.getElementById('allocation-items-empty');

        if (!prefix || !totalInput || !tableBody || !emptyTemplate) {
            return null;
        }

        return {
            formsetContainer,
            prefix,
            totalInput,
            tableBody,
            emptyTemplate,
        };
    }

    function isGeneratedBatchRow(row) {
        return row?.dataset.generatedBatchRow === 'true';
    }

    function ensureBatchGroupId(row) {
        if (!row.dataset.batchGroupId) {
            row.dataset.batchGroupId = `allocation-batch-${batchGroupCounter++}`;
        }
        return row.dataset.batchGroupId;
    }

    function getAllocationRows({ includeGenerated = true } = {}) {
        const state = getAllocationFormsetState();
        if (!state) return [];
        return Array.from(state.tableBody.querySelectorAll('.formset-row')).filter((row) => {
            const deleteCheckbox = row.querySelector('[name$="-DELETE"]');
            if (deleteCheckbox && deleteCheckbox.checked) return false;
            if (!includeGenerated && isGeneratedBatchRow(row)) return false;
            if (row.classList.contains('d-none') && !isGeneratedBatchRow(row)) return false;
            return true;
        });
    }

    function getPrimaryAllocationRows() {
        return getAllocationRows({ includeGenerated: false });
    }

    function getMatchingStocks(itemId) {
        return stockCatalog.filter((stock) => String(stock.itemId) === String(itemId));
    }

    function getStockMeta(stockId) {
        return stockCatalog.find((stock) => String(stock.id) === String(stockId)) || null;
    }

    function getGeneratedRowsForGroup(row) {
        const groupId = ensureBatchGroupId(row);
        return getAllocationRows({ includeGenerated: true }).filter((candidate) => {
            return candidate !== row && isGeneratedBatchRow(candidate) && candidate.dataset.batchGroupId === groupId;
        });
    }

    function setRowDeleted(row, deleted) {
        const deleteCheckbox = row.querySelector('[name$="-DELETE"]');
        if (deleteCheckbox) {
            deleteCheckbox.checked = deleted;
        }
        row.classList.toggle('d-none', deleted);
    }

    function clearGeneratedRowsForGroup(row) {
        getGeneratedRowsForGroup(row).forEach((generatedRow) => setRowDeleted(generatedRow, true));
    }

    function syncRowSelection(row, itemId, stockId = '') {
        const itemSelect = row.querySelector('.js-item-select');
        const stockSelect = row.querySelector('.js-stock-select');
        if (!itemSelect || !stockSelect) return;

        itemSelect.value = String(itemId || '');
        itemSelect.dispatchEvent(new Event('change', { bubbles: true }));

        if (stockId) {
            stockSelect.value = String(stockId);
        }
        stockSelect.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function createAllocationItemRow(itemId = '', stockId = '', options = {}) {
        const state = getAllocationFormsetState();
        if (!state) return null;

        const index = parseInt(state.totalInput.value, 10);
        const html = state.emptyTemplate.innerHTML.replace(/__prefix__/g, String(index));
        const wrapper = document.createElement('tbody');
        wrapper.innerHTML = html.trim();
        const row = wrapper.querySelector('tr');
        if (!row) return null;

        state.tableBody.appendChild(row);
        state.totalInput.value = String(index + 1);

        if (options.generated) {
            row.dataset.generatedBatchRow = 'true';
            row.dataset.batchGroupId = options.groupId || '';
            row.classList.add('d-none');
        }

        if (typeof initTypeaheadSelects === 'function') {
            initTypeaheadSelects();
        }
        if (typeof initStockByItemFilter === 'function') {
            initStockByItemFilter();
        }

        if (itemId) {
            syncRowSelection(row, itemId, stockId);
        }

        return row;
    }

    function getSelectedStockIdsForGroup(row) {
        const selectedIds = [];
        const stockSelect = row.querySelector('.js-stock-select');
        if (stockSelect?.value) {
            selectedIds.push(String(stockSelect.value));
        }
        getGeneratedRowsForGroup(row).forEach((generatedRow) => {
            const generatedStockSelect = generatedRow.querySelector('.js-stock-select');
            if (generatedStockSelect?.value) {
                selectedIds.push(String(generatedStockSelect.value));
            }
        });
        return selectedIds;
    }

    function updateVisibleQtyForGroup(row) {
        const qtyCell = row.querySelector('.js-available-qty');
        if (!qtyCell) return;

        const totalAvailable = getSelectedStockIdsForGroup(row)
            .map((stockId) => getStockMeta(stockId)?.availableQty || 0)
            .reduce((sum, qty) => sum + qty, 0);

        qtyCell.textContent = totalAvailable > 0 ? String(totalAvailable) : '—';
    }

    function closeBatchPicker(row) {
        const picker = row.querySelector('.js-batch-picker');
        const panel = row.querySelector('.js-batch-picker-panel');
        if (!picker || !panel) return;
        picker.classList.remove('is-open');
        panel.classList.add('d-none');
    }

    function updateBatchPickerSummary(row) {
        const summaryEl = row.querySelector('.js-batch-picker-summary');
        const trigger = row.querySelector('.js-batch-picker-toggle');
        const selectedIds = getSelectedStockIdsForGroup(row);
        const itemSelect = row.querySelector('.js-item-select');
        if (!summaryEl || !trigger || !itemSelect) return;

        if (!itemSelect.value) {
            summaryEl.textContent = 'Pilih barang terlebih dahulu';
            trigger.disabled = true;
            return;
        }

        trigger.disabled = false;
        if (selectedIds.length === 0) {
            summaryEl.textContent = 'Pilih batch stok';
            return;
        }

        if (selectedIds.length === 1) {
            summaryEl.textContent = getStockMeta(selectedIds[0])?.label || '1 batch dipilih';
            return;
        }

        summaryEl.textContent = `${selectedIds.length} batch dipilih`;
    }

    function renderBatchPicker(row) {
        const picker = row.querySelector('.js-batch-picker');
        const panel = row.querySelector('.js-batch-picker-panel');
        const listEl = row.querySelector('.js-batch-checkbox-list');
        const emptyEl = row.querySelector('.js-batch-checkbox-empty');
        const trigger = row.querySelector('.js-batch-picker-toggle');
        const itemSelect = row.querySelector('.js-item-select');
        if (!picker || !panel || !listEl || !emptyEl || !trigger || !itemSelect) return;

        const itemId = itemSelect.value;
        const matchingStocks = itemId ? getMatchingStocks(itemId) : [];
        const selectedIds = new Set(getSelectedStockIdsForGroup(row));

        listEl.innerHTML = '';
        if (!itemId) {
            emptyEl.textContent = 'Pilih barang terlebih dahulu.';
            emptyEl.classList.remove('d-none');
            trigger.disabled = true;
            updateBatchPickerSummary(row);
            updateVisibleQtyForGroup(row);
            return;
        }

        trigger.disabled = matchingStocks.length === 0;

        if (matchingStocks.length === 0) {
            emptyEl.textContent = 'Tidak ada batch stok tersedia untuk barang ini.';
            emptyEl.classList.remove('d-none');
            updateBatchPickerSummary(row);
            updateVisibleQtyForGroup(row);
            return;
        }

        emptyEl.classList.add('d-none');

        matchingStocks.forEach((stock) => {
            const item = document.createElement('label');
            item.className = 'batch-checkbox-item';
            item.dataset.stockId = String(stock.id);
            item.classList.toggle('is-selected', selectedIds.has(String(stock.id)));

            const formCheck = document.createElement('span');
            formCheck.className = 'form-check';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'form-check-input js-batch-checkbox';
            checkbox.value = String(stock.id);
            checkbox.checked = selectedIds.has(String(stock.id));

            const textWrap = document.createElement('span');
            const title = document.createElement('span');
            title.className = 'batch-checkbox-item-title';
            title.textContent = stock.label.split('|')[0].trim();

            const description = document.createElement('span');
            description.className = 'batch-checkbox-item-description';
            description.textContent = stock.label;

            textWrap.appendChild(title);
            textWrap.appendChild(description);
            formCheck.appendChild(checkbox);
            formCheck.appendChild(textWrap);
            item.appendChild(formCheck);
            listEl.appendChild(item);
        });

        updateBatchPickerSummary(row);
        updateVisibleQtyForGroup(row);
    }

    function syncBatchSelections(row) {
        const itemSelect = row.querySelector('.js-item-select');
        const picker = row.querySelector('.js-batch-picker');
        const stockSelect = row.querySelector('.js-stock-select');
        if (!itemSelect || !picker || !stockSelect) return;

        const itemId = itemSelect.value;
        if (!itemId) {
            stockSelect.value = '';
            stockSelect.dispatchEvent(new Event('change', { bubbles: true }));
            clearGeneratedRowsForGroup(row);
            renderBatchPicker(row);
            return;
        }

        const selectedIds = Array.from(
            picker.querySelectorAll('.js-batch-checkbox:checked')
        ).map((checkbox) => checkbox.value);

        const matchingStocks = getMatchingStocks(itemId).map((stock) => String(stock.id));
        const orderedSelectedIds = matchingStocks.filter((stockId) => selectedIds.includes(stockId));

        clearGeneratedRowsForGroup(row);

        if (orderedSelectedIds.length === 0) {
            stockSelect.value = '';
            stockSelect.dispatchEvent(new Event('change', { bubbles: true }));
            renderBatchPicker(row);
            refreshDerivedViews();
            return;
        }

        syncRowSelection(row, itemId, orderedSelectedIds[0]);

        orderedSelectedIds.slice(1).forEach((stockId) => {
            createAllocationItemRow(itemId, stockId, {
                generated: true,
                groupId: ensureBatchGroupId(row),
            });
        });

        renderBatchPicker(row);
        refreshDerivedViews();
    }

    document.addEventListener('click', (e) => {
        const pickerToggle = e.target.closest('.js-batch-picker-toggle');
        if (pickerToggle) {
            const row = pickerToggle.closest('.formset-row');
            const picker = row?.querySelector('.js-batch-picker');
            const panel = row?.querySelector('.js-batch-picker-panel');
            if (!row || !picker || !panel || pickerToggle.disabled) return;

            const shouldOpen = panel.classList.contains('d-none');
            getPrimaryAllocationRows().forEach((candidateRow) => {
                if (candidateRow !== row) closeBatchPicker(candidateRow);
            });
            picker.classList.toggle('is-open', shouldOpen);
            panel.classList.toggle('d-none', !shouldOpen);
            return;
        }

        if (!e.target.closest('.js-batch-picker')) {
            getPrimaryAllocationRows().forEach((row) => closeBatchPicker(row));
        }

        const removeButton = e.target.closest('.formset-remove');
        if (removeButton) {
            const row = removeButton.closest('.formset-row');
            if (row && !isGeneratedBatchRow(row)) {
                window.setTimeout(() => {
                    clearGeneratedRowsForGroup(row);
                    refreshDerivedViews();
                }, 0);
            }
            return;
        }

        if (e.target.closest('.formset-clear')) {
            window.setTimeout(() => {
                getPrimaryAllocationRows().forEach((row) => {
                    clearGeneratedRowsForGroup(row);
                    renderBatchPicker(row);
                });
                refreshDerivedViews();
            }, 0);
        }
    });

    document.addEventListener('change', (e) => {
        if (e.target.matches('.js-batch-checkbox')) {
            const row = e.target.closest('.formset-row');
            const item = e.target.closest('.batch-checkbox-item');
            if (item) item.classList.toggle('is-selected', e.target.checked);
            if (!row) return;
            syncBatchSelections(row);
            return;
        }

        if (!e.target.matches('.js-item-select, .js-stock-select')) return;
        const row = e.target.closest('.formset-row');
        if (!row) return;

        if (e.target.matches('.js-item-select') && !isGeneratedBatchRow(row)) {
            clearGeneratedRowsForGroup(row);
            const stockSelect = row.querySelector('.js-stock-select');
            if (stockSelect) {
                stockSelect.value = '';
                stockSelect.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }

        if (!isGeneratedBatchRow(row)) {
            renderBatchPicker(row);
        }
    });

    window.setTimeout(() => {
        getPrimaryAllocationRows().forEach((row) => {
            ensureBatchGroupId(row);
            renderBatchPicker(row);
        });
    }, 0);

    function refreshDerivedViews() {
        if (document.getElementById('step-3')?.classList.contains('active')) buildMatrix();
        if (document.getElementById('step-4')?.classList.contains('active')) buildReview();
    }

    function getSelectionTitle(item, fallback = '') {
        return item?.querySelector('.selection-item-title')?.textContent?.trim()
            || item?.querySelector('.form-check-label')?.textContent?.trim()
            || fallback;
    }

    function enhancePickerList(listId, metadata) {
        const listEl = document.getElementById(listId);
        if (!listEl) return;

        getPickerItems(listEl).forEach(item => {
            const checkbox = item.querySelector('input[type="checkbox"]');
            const label = item.querySelector('.form-check-label');
            if (!checkbox || !label) return;

            const meta = metadata[String(checkbox.value)];
            if (!meta) return;

            label.innerHTML = `
                <span class="selection-item-text">
                    <span class="selection-item-title">${escapeHtml(meta.title)}</span>
                    <span class="selection-item-description">${escapeHtml(meta.description)}</span>
                </span>
            `;
            item.dataset.selectionLabel = `${meta.title} ${meta.description}`.toLowerCase();
        });
    }

    function getPickerItems(listEl) {
        return Array.from(listEl.querySelectorAll('.selection-picker-item'));
    }

    function getVisiblePickerItems(listEl) {
        return getPickerItems(listEl).filter(item => !item.classList.contains('d-none'));
    }

    function updatePickerSummary(listEl) {
        const picker = listEl.closest('.selection-picker');
        const summaryEl = picker?.querySelector('.js-selection-summary');
        if (!summaryEl) return;

        const checkedItems = getPickerItems(listEl).filter(item => item.querySelector('input[type="checkbox"]:checked'));
        const emptySummary = summaryEl.dataset.emptySummary || 'Belum ada pilihan';

        if (checkedItems.length === 0) {
            summaryEl.textContent = emptySummary;
            return;
        }

        summaryEl.textContent = `${checkedItems.length} dipilih`;
    }

    function updatePickerItemState(checkbox) {
        const item = checkbox.closest('.selection-picker-item');
        if (!item) return;
        item.classList.toggle('is-selected', checkbox.checked);
    }

    function updatePickerEmptyState(listEl) {
        const emptyEl = listEl.querySelector('.selection-picker-empty');
        if (!emptyEl) return;
        emptyEl.classList.toggle('d-none', getVisiblePickerItems(listEl).length > 0);
    }

    function handlePickerFilter(input) {
        const listEl = document.getElementById(input.dataset.selectionFilterTarget || '');
        if (!listEl) return;

        const term = input.value.trim().toLowerCase();
        getPickerItems(listEl).forEach(item => {
            const label = item.dataset.selectionLabel || '';
            item.classList.toggle('d-none', Boolean(term) && !label.includes(term));
        });

        updatePickerEmptyState(listEl);
    }

    function applyBulkSelection(button) {
        const listEl = document.getElementById(button.dataset.selectionTarget || '');
        if (!listEl) return;

        const shouldSelect = button.dataset.selectionAction === 'select-all';
        getVisiblePickerItems(listEl).forEach(item => {
            const checkbox = item.querySelector('input[type="checkbox"]');
            if (!checkbox || checkbox.disabled) return;
            checkbox.checked = shouldSelect;
            updatePickerItemState(checkbox);
        });

        updatePickerSummary(listEl);
        refreshDerivedViews();
    }

    function initializeSelectionPickers() {
        enhancePickerList('allocation-facility-list', facilityPickerMeta);
        enhancePickerList('allocation-staff-list', staffPickerMeta);

        document.querySelectorAll('.selection-picker-list').forEach(listEl => {
            getPickerItems(listEl).forEach(item => {
                const checkbox = item.querySelector('input[type="checkbox"]');
                if (checkbox) updatePickerItemState(checkbox);
            });
            updatePickerSummary(listEl);
            updatePickerEmptyState(listEl);
        });

        document.querySelectorAll('.js-selection-filter').forEach(input => {
            input.addEventListener('input', () => handlePickerFilter(input));
        });

        document.querySelectorAll('.js-selection-bulk-action').forEach(button => {
            button.addEventListener('click', () => applyBulkSelection(button));
        });

        document.addEventListener('change', (e) => {
            if (!e.target.matches('.selection-picker input[type="checkbox"]')) return;
            const listEl = e.target.closest('.selection-picker-list');
            if (!listEl) return;

            updatePickerItemState(e.target);
            updatePickerSummary(listEl);
            refreshDerivedViews();
        });
    }

    initializeSelectionPickers();

    // ────────────────────────────────────
    // Matrix building (Step 3)
    // ────────────────────────────────────

    function getSelectedFacilities() {
        const facilities = [];
        document.querySelectorAll('#allocation-facility-list input[type="checkbox"]:checked')
            .forEach(cb => {
                const label = cb.closest('.selection-picker-item');
                const name = getSelectionTitle(label, cb.value);
                facilities.push({ id: cb.value, name: name });
            });
        return facilities;
    }

    function getDisplayGroupsForStep2() {
        return getPrimaryAllocationRows()
            .map((row) => {
                const itemSelect = row.querySelector('.js-item-select');
                const stockSelect = row.querySelector('.js-stock-select');

                if (!itemSelect || !itemSelect.value || !stockSelect || !stockSelect.value) {
                    return null;
                }

                return {
                    row,
                    itemId: itemSelect.value,
                    selectedStockIds: getSelectedStockIdsForGroup(row),
                };
            })
            .filter(Boolean);
    }

    function buildBatchMatrixItem(row) {
        const itemSelect = row.querySelector('.js-item-select');
        const stockSelect = row.querySelector('.js-stock-select');
        const idField = row.querySelector('[name$="-id"]');

        if (!itemSelect || !itemSelect.value) return null;
        if (!stockSelect || !stockSelect.value) return null;

        const itemText = itemSelect.options[itemSelect.selectedIndex]?.text || '';
        const stockText = stockSelect.options[stockSelect.selectedIndex]?.text || '';
        const stockMeta = getStockMeta(stockSelect.value);
        const available = stockMeta?.availableQty || 0;

        return {
            formIndex: idField?.value || itemSelect.name?.match(/items-(\d+)-/)?.[1] || '',
            itemId: itemSelect.value,
            itemName: itemText,
            stockId: stockSelect.value || '',
            stockLabel: stockText,
            available: available,
            stockOrder: stockCatalog.findIndex((stock) => String(stock.id) === String(stockSelect.value)),
        };
    }

    function getBatchMatrixItems() {
        return getPrimaryAllocationRows().flatMap((row) => {
            const groupRows = [row, ...getGeneratedRowsForGroup(row)]
                .map((candidateRow) => buildBatchMatrixItem(candidateRow))
                .filter(Boolean)
                .sort((left, right) => left.stockOrder - right.stockOrder);

            return groupRows;
        });
    }

    function buildMatrix() {
        const facilities = getSelectedFacilities();
        const items = getBatchMatrixItems();
        const headerRow = document.getElementById('matrix-header-row');
        const matrixBody = document.getElementById('matrix-body');
        const emptyMsg = document.getElementById('matrix-empty-msg');

        if (!headerRow || !matrixBody) return;

        // Clear dynamic columns
        headerRow.querySelectorAll('.js-facility-col').forEach(el => el.remove());

        // Insert facility columns before "Total"
        const totalTh = headerRow.lastElementChild;
        facilities.forEach(f => {
            const th = document.createElement('th');
            th.textContent = f.name;
            th.classList.add('js-facility-col');
            headerRow.insertBefore(th, totalTh);
        });

        matrixBody.innerHTML = '';

        if (items.length === 0 || facilities.length === 0) {
            if (emptyMsg) {
                if (items.length === 0 && facilities.length === 0) {
                    emptyMsg.textContent = 'Pilih item pada Step 2 dan fasilitas pada Step 1 terlebih dahulu.';
                } else if (items.length === 0) {
                    emptyMsg.textContent = 'Pilih item dan batch pada Step 2 terlebih dahulu.';
                } else {
                    emptyMsg.textContent = 'Pilih minimal 1 fasilitas pada Step 1 terlebih dahulu.';
                }
                emptyMsg.classList.remove('d-none');
            }
            return;
        }
        if (emptyMsg) emptyMsg.classList.add('d-none');

        items.forEach(item => {
            const tr = document.createElement('tr');

            // Item name + batch
            const tdItem = document.createElement('td');
            tdItem.classList.add('text-start');
            tdItem.innerHTML = `<div>${escapeHtml(item.itemName)}</div><small class="text-muted">${escapeHtml(item.stockLabel)}</small>`;
            tr.appendChild(tdItem);

            // Available
            const tdAvail = document.createElement('td');
            tdAvail.textContent = item.available;
            tdAvail.classList.add('fw-semibold');
            tr.appendChild(tdAvail);

            // Facility quantity inputs
            let totalAllocated = 0;
            const inputCells = [];
            facilities.forEach(f => {
                const td = document.createElement('td');
                td.classList.add('js-facility-col');
                const input = document.createElement('input');
                input.type = 'number';
                input.min = '0';
                input.classList.add('form-control', 'form-control-sm', 'js-matrix-qty');
                input.name = `alloc_${item.formIndex}_${f.id}`;
                input.dataset.itemIndex = item.formIndex;
                input.dataset.facilityId = f.id;

                // Restore existing value
                const existingKey = `${item.formIndex}_${f.id}`;
                if (existingAllocations[existingKey]) {
                    input.value = existingAllocations[existingKey];
                    totalAllocated += existingAllocations[existingKey];
                } else {
                    input.value = '';
                }

                input.addEventListener('input', () => updateRowTotal(tr, item.available));
                td.appendChild(input);
                tr.appendChild(td);
                inputCells.push(input);
            });

            // Total column
            const tdTotal = document.createElement('td');
            tdTotal.classList.add('fw-semibold', 'js-row-total');
            tdTotal.textContent = totalAllocated || 0;
            tr.appendChild(tdTotal);

            matrixBody.appendChild(tr);
            updateRowTotal(tr, item.available);
        });
    }

    function updateRowTotal(tr, available) {
        const inputs = tr.querySelectorAll('.js-matrix-qty');
        let total = 0;
        inputs.forEach(input => {
            total += parseInt(input.value) || 0;
        });

        const totalCell = tr.querySelector('.js-row-total');
        if (totalCell) {
            totalCell.textContent = total;
            if (total > available) {
                totalCell.classList.add('text-danger');
                tr.classList.add('over-allocated');
            } else {
                totalCell.classList.remove('text-danger');
                tr.classList.remove('over-allocated');
            }
        }
    }

    // ────────────────────────────────────
    // Review building (Step 4)
    // ────────────────────────────────────

    function buildReview() {
        buildReviewHeader();
        buildReviewMatrix();
    }

    function buildReviewHeader() {
        const container = document.getElementById('review-header-content');
        if (!container) return;

        const title = document.getElementById('id_title');
        const tanggal = document.getElementById('id_allocation_date');
        const referensi = document.getElementById('id_referensi');
        const notes = document.getElementById('id_notes');
        const facilities = getSelectedFacilities();
        const staffChecked = document.querySelectorAll('#allocation-staff-list input[type="checkbox"]:checked');

        const staffNames = [];
        staffChecked.forEach(cb => {
            const label = cb.closest('.selection-picker-item');
            staffNames.push(getSelectionTitle(label, cb.value));
        });

        container.innerHTML = `
            <div class="row g-2 small">
                <div class="col-12"><strong>Judul:</strong> ${escapeHtml(title?.value || '—')}</div>
                <div class="col-md-4"><strong>Tanggal:</strong> ${escapeHtml(tanggal?.value || '—')}</div>
                <div class="col-md-4"><strong>Referensi:</strong> ${escapeHtml(referensi?.value || '—')}</div>
                <div class="col-md-6"><strong>Fasilitas:</strong> ${facilities.map(f => escapeHtml(f.name)).join(', ') || '—'}</div>
                <div class="col-md-6"><strong>Petugas:</strong> ${staffNames.map(n => escapeHtml(n)).join(', ') || '—'}</div>
                ${notes?.value ? `<div class="col-12"><strong>Catatan:</strong> ${escapeHtml(notes.value)}</div>` : ''}
            </div>
        `;
    }

    function buildReviewMatrix() {
        const container = document.getElementById('review-matrix-content');
        if (!container) return;

        const facilities = getSelectedFacilities();
        const items = getBatchMatrixItems();

        if (items.length === 0 || facilities.length === 0) {
            container.innerHTML = '<div class="text-muted small">Tidak ada data untuk ditampilkan.</div>';
            return;
        }

        let html = '<div class="table-responsive"><table class="table table-sm table-bordered alloc-matrix">';
        html += '<thead class="table-light"><tr><th>Barang</th><th>Tersedia</th>';
        facilities.forEach(f => { html += `<th>${escapeHtml(f.name)}</th>`; });
        html += '<th>Total</th></tr></thead><tbody>';

        items.forEach(item => {
            html += '<tr>';
            html += `<td class="text-start">${escapeHtml(item.itemName)}<br><small class="text-muted">${escapeHtml(item.stockLabel)}</small></td>`;
            html += `<td>${item.available}</td>`;

            let rowTotal = 0;
            facilities.forEach(f => {
                const input = document.querySelector(`input[name="alloc_${item.formIndex}_${f.id}"]`);
                const val = parseInt(input?.value) || 0;
                rowTotal += val;
                html += `<td>${val || '—'}</td>`;
            });

            const isOver = rowTotal > item.available;
            html += `<td class="fw-semibold ${isOver ? 'text-danger' : ''}">${rowTotal}</td>`;
            html += '</tr>';
        });

        html += '</tbody></table></div>';
        container.innerHTML = html;
    }

    // ────────────────────────────────────
    // Utility
    // ────────────────────────────────────


    window.__allocationWizardTestApi = {
        getDisplayGroupsForStep2,
        getBatchMatrixItems,
        buildMatrix,
        buildReviewMatrix,
        buildReview,
        goToStep,
    };
    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAllocationForm, { once: true });
} else {
    initAllocationForm();
}






