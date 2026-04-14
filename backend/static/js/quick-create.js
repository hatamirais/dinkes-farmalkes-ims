/**
 * Shared quick-create modal helpers for receiving and distribution forms.
 * Templates pass URLs via data-* attributes on the save buttons.
 *
 * Expected data attributes on save buttons:
 *   data-url         – POST endpoint URL
 *   data-fields      – comma-separated list of input IDs to collect (e.g. "supplier-code,supplier-name")
 *   data-field-names – comma-separated list of POST field names       (e.g. "code,name")
 *   data-error-el    – ID of the error display element
 *   data-modal-id    – ID of the modal to close
 *   data-select-id   – ID of the <select> to append the new option to
 */
function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : '';
}

async function postFormJson(url, body) {
    var response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': getCsrfToken(),
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: body,
    });

    var contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
        var text = await response.text();
        throw new Error('Server mengembalikan respons tidak valid (' + response.status + '). ' + text.slice(0, 120));
    }

    var data = await response.json();
    return { ok: response.ok, status: response.status, data: data };
}

document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-quick-create]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            var url = btn.getAttribute('data-url');
            var fieldIds = (btn.getAttribute('data-fields') || '').split(',');
            var fieldNames = (btn.getAttribute('data-field-names') || '').split(',');
            var errorElId = btn.getAttribute('data-error-el');
            var modalId = btn.getAttribute('data-modal-id');
            var selectId = btn.getAttribute('data-select-id');
            var uppercase = btn.getAttribute('data-uppercase-fields') || '';
            var uppercaseFields = uppercase ? uppercase.split(',') : [];

            var errorEl = document.getElementById(errorElId);
            if (errorEl) errorEl.classList.add('d-none');

            // Build form body
            var parts = [];
            for (var i = 0; i < fieldIds.length; i++) {
                var el = document.getElementById(fieldIds[i]);
                var val = el ? el.value.trim() : '';
                if (uppercaseFields.indexOf(fieldNames[i]) >= 0) val = val.toUpperCase();
                parts.push(fieldNames[i] + '=' + encodeURIComponent(val));
            }
            var body = parts.join('&');

            try {
                var result = await postFormJson(url, body);
                if (!result.ok) {
                    if (errorEl) {
                        errorEl.textContent = result.data.error;
                        errorEl.classList.remove('d-none');
                    }
                    return;
                }

                var select = document.getElementById(selectId);
                if (select) {
                    var opt = new Option(result.data.text, result.data.id, true, true);
                    select.add(opt);
                }

                // Clear fields
                fieldIds.forEach(function (id) {
                    var el = document.getElementById(id);
                    if (el) el.value = '';
                });

                // Close modal
                if (modalId) {
                    var modalEl = document.getElementById(modalId);
                    if (modalEl) {
                        var modalInstance = bootstrap.Modal.getInstance(modalEl);
                        if (modalInstance) modalInstance.hide();
                    }
                }
            } catch (err) {
                if (errorEl) {
                    errorEl.textContent = err.message || 'Gagal menyimpan.';
                    errorEl.classList.remove('d-none');
                }
            }
        });
    });
});
