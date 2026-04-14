/**
 * Puskesmas request form: dynamic formset add/remove rows
 */
document.addEventListener('DOMContentLoaded', function () {
    var totalFormsInput = document.getElementById('id_items-TOTAL_FORMS');
    var formsetBody = document.getElementById('formset-body');
    var template = document.getElementById('empty-form-template');
    var addBtn = document.getElementById('add-item-btn');

    if (!totalFormsInput || !formsetBody || !template || !addBtn) return;

    addBtn.addEventListener('click', function () {
        var idx = parseInt(totalFormsInput.value);
        var clone = template.content.cloneNode(true);

        // Replace __prefix__ with current index
        clone.querySelectorAll('[name]').forEach(function (el) {
            el.name = el.name.replace('__prefix__', idx);
            el.id = el.id.replace('__prefix__', idx);
        });
        formsetBody.appendChild(clone);
        totalFormsInput.value = idx + 1;
    });

    // Event delegation for remove row buttons
    formsetBody.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-action-remove-row]');
        if (!btn) return;
        removeRow(btn);
    });
});

function removeRow(btn) {
    var row = btn.closest('tr');
    // If it has an id (existing DB row), check for DELETE checkbox
    var deleteInput = row.querySelector('input[type=checkbox]');
    if (deleteInput) {
        deleteInput.checked = true;
        row.style.display = 'none';
    } else {
        row.remove();
        renumberForms();
    }
}

function renumberForms() {
    var formsetBody = document.getElementById('formset-body');
    if (!formsetBody) return;
    var totalFormsInput = document.getElementById('id_items-TOTAL_FORMS');
    var rows = formsetBody.querySelectorAll('tr.formset-row:not([style*="display: none"])');
    rows.forEach(function (row, idx) {
        row.querySelectorAll('[name]').forEach(function (el) {
            el.name = el.name.replace(/items-\d+-/, 'items-' + idx + '-');
            el.id = el.id.replace(/items-\d+-/, 'items-' + idx + '-');
        });
    });
    if (totalFormsInput) totalFormsInput.value = rows.length;
}
