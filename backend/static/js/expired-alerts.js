/**
 * Expired alerts page: checkbox selection and fixed-form submission logic.
 */
document.addEventListener('DOMContentLoaded', function () {
    var filterForm = document.querySelector('.filter-form');
    var pendingFilter = document.getElementById('pendingFilter');

    var selectAll = document.getElementById('selectAllExpiredRows');
    var rowChecks = function () { return Array.from(document.querySelectorAll('.expired-stock-check')); };
    var createForm = document.getElementById('createExpiredFromSelectedForm');
    var createBtn = document.getElementById('createExpiredFromSelected');
    var selectedStocksField = document.getElementById('selectedExpiredStocks');

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

    if (createBtn && createForm && selectedStocksField) {
        createForm.addEventListener('submit', function (event) {
            var selected = createBtn.dataset.selected || '';
            if (!selected) {
                event.preventDefault();
                return;
            }
            selectedStocksField.value = selected;
        });
    }

    if (pendingFilter && filterForm) {
        pendingFilter.addEventListener('change', function () {
            filterForm.submit();
        });
    }
});
