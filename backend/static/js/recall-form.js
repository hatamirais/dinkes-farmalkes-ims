document.addEventListener('DOMContentLoaded', () => {
    initRecallItemTable();
});

function initRecallItemTable() {
    const form = document.querySelector('form[data-recall-form]');
    if (!form) return;

    const formsetContainer = form.querySelector('[data-formset="recall-items"]');
    const tableBody = formsetContainer?.querySelector('tbody');
    const tableError = form.querySelector('.js-recall-table-error');
    if (!formsetContainer || !tableBody || !tableError) return;

    const getRows = () => Array.from(tableBody.querySelectorAll('tr.formset-row'));

    const getRowFields = (row) => ({
        item: row.querySelector('select.js-item-select'),
        stock: row.querySelector('select.js-stock-select'),
        quantity: row.querySelector('input[name$="-quantity"]'),
        notes: row.querySelector('input[name$="-notes"], textarea[name$="-notes"]'),
        dependentCells: row.querySelectorAll('.js-recall-dependent-cell'),
        quantityError: row.querySelector('.js-recall-quantity-error'),
    });

    const getVisibleRows = () => getRows().filter((row) => !row.classList.contains('d-none'));

    const showTableError = (show) => {
        tableError.classList.toggle('d-none', !show);
    };

    const clearQuantityError = (row) => {
        const { quantity, quantityError } = getRowFields(row);
        if (quantity) {
            quantity.classList.remove('recall-input-error');
        }
        if (quantityError) {
            quantityError.classList.add('d-none');
        }
    };

    const showQuantityError = (row) => {
        const { quantity, quantityError } = getRowFields(row);
        if (quantity) {
            quantity.classList.add('recall-input-error');
        }
        if (quantityError) {
            quantityError.classList.remove('d-none');
        }
    };

    const syncRowState = (row, options = {}) => {
        const { item, stock, quantity, notes, dependentCells } = getRowFields(row);
        if (!item) return;

        const hasItem = Boolean(item.value);
        const shouldFocusStock = Boolean(options.focusStock && hasItem);
        const dependentFields = [stock, quantity, notes].filter(Boolean);

        dependentFields.forEach((field) => {
            field.disabled = !hasItem;
        });

        dependentCells.forEach((cell) => {
            cell.classList.toggle('is-disabled', !hasItem);
        });

        row.dataset.hasConfirmedItem = hasItem ? 'true' : 'false';

        if (!hasItem) {
            clearQuantityError(row);
        }

        if (shouldFocusStock && stock && !stock.disabled) {
            window.setTimeout(() => stock.focus(), 0);
        }
    };

    const bindRow = (row) => {
        if (!row || row.dataset.recallRowBound === 'true') return;
        row.dataset.recallRowBound = 'true';

        const { item, quantity } = getRowFields(row);

        syncRowState(row);

        if (item) {
            item.addEventListener('change', () => {
                const wasActive = row.dataset.hasConfirmedItem === 'true';
                syncRowState(row, { focusStock: !wasActive });
                if (item.value) {
                    showTableError(false);
                }
            });
        }

        if (quantity) {
            quantity.addEventListener('input', () => {
                clearQuantityError(row);
            });
            quantity.addEventListener('change', () => {
                clearQuantityError(row);
            });
        }
    };

    const validateRows = () => {
        let hasAnyItem = false;
        let isValid = true;

        getVisibleRows().forEach((row) => {
            const { item, quantity } = getRowFields(row);
            if (!item || !quantity) return;

            clearQuantityError(row);

            if (!item.value) {
                return;
            }

            hasAnyItem = true;
            const quantityValue = (quantity.value || '').trim();
            if (!quantityValue || Number(quantityValue) <= 0) {
                showQuantityError(row);
                isValid = false;
            }
        });

        showTableError(!hasAnyItem);
        if (!hasAnyItem) {
            return false;
        }

        return isValid;
    };

    const refreshRows = () => {
        getRows().forEach(bindRow);
    };

    refreshRows();

    const observer = new MutationObserver(() => {
        refreshRows();
    });
    observer.observe(tableBody, { childList: true });

    form.addEventListener('submit', (event) => {
        if (validateRows()) {
            return;
        }

        event.preventDefault();

        const tableErrorVisible = !tableError.classList.contains('d-none');
        if (tableErrorVisible) {
            tableError.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            return;
        }

        const firstInvalidQuantity = form.querySelector('.recall-input-error');
        if (firstInvalidQuantity) {
            firstInvalidQuantity.focus();
        }
    });
}