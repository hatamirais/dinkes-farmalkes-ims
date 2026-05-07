/**
 * User list: inline AJAX active toggle, sortable columns, bulk actions,
 * Bootstrap modal delete, and tooltips.
 */
document.addEventListener('DOMContentLoaded', function () {
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.forEach(function (el) {
        new bootstrap.Tooltip(el);
    });

    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function getSafeDeleteUrl(rawUrl) {
        if (!rawUrl) return null;
        try {
            var parsed = new URL(rawUrl, window.location.origin);
            var isHttp = parsed.protocol === 'http:' || parsed.protocol === 'https:';
            var isSameOrigin = parsed.origin === window.location.origin;
            if (!isHttp || !isSameOrigin) return null;

            var normalized = parsed.pathname + parsed.search + parsed.hash;
            if (/[<>"'`\\]/.test(normalized)) return null;
            if (normalized.charAt(0) !== '/') return null;

            return normalized;
        } catch (e) {
            return null;
        }
    }

    function createStatusBadge(isActive) {
        var badge = document.createElement('span');
        badge.className = isActive
            ? 'badge bg-success-subtle text-success'
            : 'badge bg-secondary-subtle text-secondary';
        badge.textContent = isActive ? 'Aktif' : 'Nonaktif';
        return badge;
    }

    function setBadge(container, isActive) {
        if (!container) return;
        container.replaceChildren(createStatusBadge(Boolean(isActive)));
    }

    // ── Sortable column headers ────────────────────────────────────
    document.querySelectorAll('.sortable-header').forEach(function (th) {
        th.addEventListener('click', function () {
            var sort = this.getAttribute('data-sort');
            var params = new URLSearchParams(window.location.search);
            var currentSort = params.get('sort') || '';
            var currentOrder = params.get('order') || 'asc';

            if (sort === currentSort) {
                params.set('order', currentOrder === 'asc' ? 'desc' : 'asc');
            } else {
                params.set('sort', sort);
                params.set('order', 'asc');
            }
            params.delete('page');

            window.location.search = params.toString();
        });
    });

    // ── Bulk action bar ────────────────────────────────────────────
    var bulkBar = document.getElementById('bulkActionBar');
    var selectedCount = bulkBar ? bulkBar.querySelector('.selected-count') : null;
    var allCheckboxes = document.querySelectorAll('.user-checkbox');
    var selectAll = document.getElementById('selectAll');
    var bulkActionForm = document.getElementById('bulkActionForm');
    var bulkActionField = document.getElementById('bulkActionField');

    function updateBulkBar() {
        if (!bulkBar) return;
        var checked = document.querySelectorAll('.user-checkbox:checked');
        var count = checked.length;
        if (selectAll) {
            selectAll.checked = count > 0 && count === allCheckboxes.length;
            selectAll.indeterminate = count > 0 && count < allCheckboxes.length;
        }
        if (count > 0) {
            bulkBar.classList.remove('d-none');
            if (selectedCount) selectedCount.textContent = count + ' dipilih';
        } else {
            bulkBar.classList.add('d-none');
            if (selectedCount) selectedCount.textContent = '0 dipilih';
        }
    }

    if (allCheckboxes.length) {
        allCheckboxes.forEach(function (cb) {
            cb.addEventListener('change', updateBulkBar);
        });
    }

    if (selectAll) {
        selectAll.addEventListener('change', function () {
            allCheckboxes.forEach(function (cb) {
                cb.checked = selectAll.checked;
            });
            updateBulkBar();
        });
    }
    updateBulkBar();

    document.querySelectorAll('.bulk-action-btn[data-action]:not([data-bs-toggle])').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var action = this.getAttribute('data-action');
            if (bulkActionField) bulkActionField.value = action;
            if (bulkActionForm) bulkActionForm.submit();
        });
    });

    // ── Bulk delete modal confirm ─────────────────────────────────
    var bulkDeleteConfirm = document.getElementById('bulkDeleteConfirm');
    if (bulkDeleteConfirm) {
        bulkDeleteConfirm.addEventListener('click', function () {
            if (bulkActionField) bulkActionField.value = 'delete';
            if (bulkActionForm) bulkActionForm.submit();
        });
    }

    // ── Single delete with Bootstrap modal ─────────────────────────
    var deleteModal = document.getElementById('deleteConfirmModal');
    var deleteConfirmForm = document.getElementById('deleteConfirmForm');
    var deleteConfirmMessage = document.getElementById('deleteConfirmMessage');

    if (deleteModal && deleteConfirmForm) {
        document.querySelectorAll('.single-delete-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var rawUrl = this.getAttribute('data-delete-url');
                var safeUrl = getSafeDeleteUrl(rawUrl);
                var username = this.getAttribute('data-username');
                if (!safeUrl) {
                    return;
                }
                if (safeUrl.charAt(0) !== '/' || /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(safeUrl)) {
                    return;
                }
                deleteConfirmForm.action = safeUrl;
                if (deleteConfirmMessage) {
                    deleteConfirmMessage.textContent = 'Apakah Anda yakin ingin menghapus pengguna "' + username + '" secara permanen? Tindakan ini tidak dapat dibatalkan.';
                }
                var modal = new bootstrap.Modal(deleteModal);
                modal.show();
            });
        });
    }

    // ── Inline AJAX active toggle ──────────────────────────────────
    document.querySelectorAll('.user-active-toggle').forEach(function (toggle) {
        toggle.addEventListener('change', function () {
            var url = this.getAttribute('data-url');
            var isActive = this.checked;
            var label = this.parentElement.querySelector('.form-check-label');
            var switchEl = this;
            var wasDisabled = switchEl.disabled;

            switchEl.disabled = true;

            fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCsrfToken(),
                },
                body: 'csrfmiddlewaretoken=' + encodeURIComponent(getCsrfToken()),
            })
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error('Request failed');
                    }
                    return response.json();
                })
                .then(function (data) {
                    if (data.success) {
                        setBadge(label, data.is_active);
                    } else {
                        switchEl.checked = !isActive;
                        setBadge(label, !isActive);
                    }
                })
                .catch(function () {
                    switchEl.checked = !isActive;
                    setBadge(label, !isActive);
                })
                .finally(function () {
                    switchEl.disabled = wasDisabled;
                });
        });
    });
});
