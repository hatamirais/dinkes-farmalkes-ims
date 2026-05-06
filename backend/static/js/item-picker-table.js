document.addEventListener('DOMContentLoaded', () => {
    initItemPickerTables();
});

function initItemPickerTables() {
    document.querySelectorAll('form[data-item-picker-table="true"]').forEach((form) => {
        bindItemPickerTable(form);
    });
}

function bindItemPickerTable(form) {
    if (!form || form.dataset.itemPickerTableBound === 'true') {
        return;
    }

    const target = form.dataset.itemTableTarget;
    const requiredFieldName = form.dataset.itemRequiredField || '';
    const requiredMessage = form.dataset.itemRequiredMessage || 'Kuantitas wajib diisi.';
    const focusFieldName = form.dataset.itemFocusField || requiredFieldName;
    const dependentFieldNames = (form.dataset.itemDependentFields || '')
        .split(',')
        .map((name) => name.trim())
        .filter(Boolean);
    const formsetContainer = form.querySelector(`[data-formset="${target}"]`);
    const tableBody = formsetContainer?.querySelector('tbody');
    const tableError = form.querySelector('.js-item-picker-table-error');

    if (!target || !formsetContainer || !tableBody || !tableError) {
        return;
    }

    form.dataset.itemPickerTableBound = 'true';

    const getRows = () => Array.from(tableBody.querySelectorAll('tr.formset-row'));
    const getVisibleRows = () => getRows().filter((row) => !row.classList.contains('d-none'));

    const getRowFields = (row) => {
        const item = row.querySelector('select.js-item-select') || row.querySelector('select.js-typeahead-select');
        const requiredInput = requiredFieldName
            ? row.querySelector(`[name$="-${requiredFieldName}"]`)
            : null;
        const focusField = focusFieldName
            ? row.querySelector(`[name$="-${focusFieldName}"]`)
            : requiredInput;
        const dependentCells = row.querySelectorAll('.js-item-picker-dependent');
        const dependentFields = dependentFieldNames
            .map((fieldName) => row.querySelector(`[name$="-${fieldName}"]`))
            .filter(Boolean);
        const fieldError = requiredFieldName
            ? row.querySelector(`.js-item-picker-field-error[data-field-name="${requiredFieldName}"]`)
            : null;

        return {
            item,
            requiredInput,
            focusField,
            dependentCells,
            dependentFields,
            fieldError,
        };
    };

    const showTableError = (show) => {
        tableError.classList.toggle('d-none', !show);
    };

    const clearRowError = (row) => {
        const { requiredInput, fieldError } = getRowFields(row);
        if (requiredInput) {
            requiredInput.classList.remove('item-picker-input-error');
        }
        if (fieldError) {
            fieldError.textContent = requiredMessage;
            fieldError.classList.add('d-none');
        }
    };

    const showRowError = (row) => {
        const { requiredInput, fieldError } = getRowFields(row);
        if (requiredInput) {
            requiredInput.classList.add('item-picker-input-error');
        }
        if (fieldError) {
            fieldError.textContent = requiredMessage;
            fieldError.classList.remove('d-none');
        }
    };

    const syncRowState = (row, options = {}) => {
        const { item, focusField, dependentCells, dependentFields } = getRowFields(row);
        if (!item) {
            return;
        }

        const hasItem = Boolean(item.value);
        dependentFields.forEach((field) => {
            field.disabled = !hasItem;
        });

        dependentCells.forEach((cell) => {
            cell.classList.toggle('is-disabled', !hasItem);
        });

        if (!hasItem) {
            clearRowError(row);
        }

        const shouldFocus = Boolean(options.focusField && hasItem && focusField && !focusField.disabled);
        if (shouldFocus) {
            window.setTimeout(() => focusField.focus(), 0);
        }
    };

    const bindRow = (row) => {
        if (!row || row.dataset.itemPickerRowBound === 'true') {
            return;
        }
        row.dataset.itemPickerRowBound = 'true';

        const { item, requiredInput } = getRowFields(row);
        syncRowState(row);

        if (item) {
            item.addEventListener('change', () => {
                const wasSelected = row.dataset.hasSelectedItem === 'true';
                row.dataset.hasSelectedItem = item.value ? 'true' : 'false';
                syncRowState(row, { focusField: !wasSelected });
                if (item.value) {
                    showTableError(false);
                }
            });
        }

        if (requiredInput) {
            const clear = () => clearRowError(row);
            requiredInput.addEventListener('input', clear);
            requiredInput.addEventListener('change', clear);
        }
    };

    const validateRows = () => {
        let hasAnyItem = false;
        let isValid = true;

        getVisibleRows().forEach((row) => {
            const { item, requiredInput } = getRowFields(row);
            if (!item) {
                return;
            }

            clearRowError(row);

            if (!item.value) {
                return;
            }

            hasAnyItem = true;
            if (!requiredInput) {
                return;
            }

            const rawValue = `${requiredInput.value || ''}`.trim();
            if (!rawValue || Number(rawValue) <= 0) {
                showRowError(row);
                isValid = false;
            }
        });

        showTableError(!hasAnyItem);
        return hasAnyItem && isValid;
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

        if (!tableError.classList.contains('d-none')) {
            tableError.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            return;
        }

        const invalidField = form.querySelector('.item-picker-input-error');
        if (invalidField) {
            invalidField.focus();
        }
    });
}