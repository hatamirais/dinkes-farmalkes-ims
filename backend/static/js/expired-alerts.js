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

    function buildSafeCreatePath(rawPath, selectedStocks) {
        if (!rawPath || rawPath.charAt(0) !== '/') return null;
        if (/^(?:[a-zA-Z][a-zA-Z0-9+.-]*:)?\/\//.test(rawPath)) return null;

        var parts = rawPath.split('?');
        var pathname = parts[0];
        if (!pathname || pathname.charAt(0) !== '/') return null;

        var params = new URLSearchParams(parts[1] || '');
        params.set('stocks', selectedStocks);
        var query = params.toString();
        return query ? pathname + '?' + query : pathname;
    }

    if (createBtn) {
        createBtn.addEventListener('click', function () {
            var selected = createBtn.dataset.selected || '';
            if (!selected) return;
            var createUrl = createBtn.getAttribute('data-create-url') || '';
            var nextPath = buildSafeCreatePath(createUrl, selected);
            if (!nextPath) return;

            window.location.assign(nextPath);
        });
    }

    if (pendingFilter && filterForm) {
        pendingFilter.addEventListener('change', function () {
            filterForm.submit();
        });
    }
});
