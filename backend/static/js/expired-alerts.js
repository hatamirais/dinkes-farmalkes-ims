/**
 * Expired alerts page: checkbox selection and create-from-selected logic
 *
 * Expected data attributes on #createExpiredFromSelected button:
 *   data-create-url – the URL for expired_create
 */
document.addEventListener('DOMContentLoaded', function () {
    var filterForm = document.querySelector('.filter-form');
    var pendingFilter = document.getElementById('pendingFilter');

    var selectAll = document.getElementById('selectAllExpiredRows');
    var rowChecks = function () { return Array.from(document.querySelectorAll('.expired-stock-check')); };
    var createBtn = document.getElementById('createExpiredFromSelected');

    function syncButtonState() {
        var selected = rowChecks().filter(function (cb) { return cb.checked; }).map(function (cb) { return cb.value; });
        createBtn.disabled = selected.length === 0;
        createBtn.dataset.selected = selected.join(',');
    }

    if (selectAll) {
        selectAll.addEventListener('change', function () {
            var checked = selectAll.checked;
            rowChecks().forEach(function (cb) { cb.checked = checked; });
            syncButtonState();
        });
    }

    rowChecks().forEach(function (cb) { cb.addEventListener('change', syncButtonState); });

    if (createBtn) {
        createBtn.addEventListener('click', function () {
            var selected = createBtn.dataset.selected || '';
            if (!selected) return;
            var createUrl = createBtn.getAttribute('data-create-url') || '';
            window.location.href = createUrl + '?stocks=' + encodeURIComponent(selected);
        });
    }

    if (pendingFilter && filterForm) {
        pendingFilter.addEventListener('change', function () {
            filterForm.submit();
        });
    }
});
