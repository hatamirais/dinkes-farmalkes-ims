/**
 * Distribution form: staff picker, quick-create facility modal
 *
 * Expected data attributes on #distribution-form-container:
 *   data-url-facility – quick create facility URL
 */
document.addEventListener('DOMContentLoaded', function () {
    // ── Staff Picker ──────────────────────────────────────────
    var updateStaffSummary = function () {
        document.querySelectorAll('.staff-picker').forEach(function (picker) {
            var summary = picker.querySelector('.js-staff-summary');
            if (!summary) return;

            var checked = Array.from(picker.querySelectorAll('input[type="checkbox"]:checked'));
            if (checked.length === 0) {
                summary.textContent = 'Belum ada petugas dipilih';
                return;
            }

            var names = checked
                .map(function (input) {
                    var label = input.closest('.staff-picker-item')?.querySelector('.form-check-label');
                    return label ? label.textContent.trim() : '';
                })
                .filter(Boolean);

            summary.textContent = checked.length + ' dipilih: ' + names.join(', ');
        });
    };

    document.querySelectorAll('.staff-picker-item').forEach(function (item) {
        var checkbox = item.querySelector('input[type="checkbox"]');
        if (!checkbox) return;

        var syncState = function () {
            item.classList.toggle('is-selected', checkbox.checked);
            updateStaffSummary();
        };

        syncState();
        checkbox.addEventListener('change', syncState);
    });

    document.querySelectorAll('.staff-picker-toggle').forEach(function (button) {
        var targetSelector = button.getAttribute('data-bs-target');
        var target = targetSelector ? document.querySelector(targetSelector) : null;
        if (!target) return;

        target.addEventListener('shown.bs.collapse', function () {
            button.setAttribute('aria-expanded', 'true');
        });

        target.addEventListener('hidden.bs.collapse', function () {
            button.setAttribute('aria-expanded', 'false');
        });
    });

    document.querySelectorAll('.js-staff-filter').forEach(function (input) {
        var targetId = input.getAttribute('data-staff-filter-target');
        var container = targetId ? document.getElementById(targetId) : null;
        if (!container) return;

        var items = Array.from(container.querySelectorAll('.staff-picker-item'));
        var emptyState = container.querySelector('.staff-picker-empty');

        input.addEventListener('input', function () {
            var query = input.value.trim().toLowerCase();
            var visibleCount = 0;

            items.forEach(function (item) {
                var label = item.getAttribute('data-staff-label') || '';
                var match = !query || label.includes(query);
                item.classList.toggle('d-none', !match);
                if (match) visibleCount += 1;
            });

            if (emptyState) {
                emptyState.classList.toggle('d-none', visibleCount > 0);
            }
        });
    });

    updateStaffSummary();

    // ── Quick-create Facility ─────────────────────────────────
    var container = document.getElementById('distribution-form-container');
    var urlFacility = container ? container.getAttribute('data-url-facility') : '';

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

    var facilitySaveBtn = document.getElementById('btn-save-facility');
    if (facilitySaveBtn && urlFacility) {
        facilitySaveBtn.addEventListener('click', async function () {
            var errorEl = document.getElementById('facility-error');
            errorEl.classList.add('d-none');

            var code = document.getElementById('facility-code').value.trim().toUpperCase();
            var name = document.getElementById('facility-name').value.trim();
            var facilityType = document.getElementById('facility-type').value;
            var phone = document.getElementById('facility-phone').value.trim();
            var address = document.getElementById('facility-address').value.trim();
            var body = 'code=' + encodeURIComponent(code)
                + '&name=' + encodeURIComponent(name)
                + '&facility_type=' + encodeURIComponent(facilityType)
                + '&phone=' + encodeURIComponent(phone)
                + '&address=' + encodeURIComponent(address);

            try {
                var result = await postFormJson(urlFacility, body);
                if (!result.ok) {
                    errorEl.textContent = result.data.error;
                    errorEl.classList.remove('d-none');
                    return;
                }

                var select = document.getElementById('id_facility');
                var opt = new Option(result.data.text, result.data.id, true, true);
                select.add(opt);
                ['code', 'name', 'phone', 'address'].forEach(function (field) {
                    document.getElementById('facility-' + field).value = '';
                });
                document.getElementById('facility-type').value = 'PUSKESMAS';
                bootstrap.Modal.getInstance(document.getElementById('modal-facility')).hide();
            } catch (err) {
                errorEl.textContent = err.message || 'Gagal menyimpan fasilitas.';
                errorEl.classList.remove('d-none');
            }
        });
    }
});
