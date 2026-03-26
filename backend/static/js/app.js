/**
 * Healthcare IMS - Application JavaScript (Vanilla JS)
 */

document.addEventListener('DOMContentLoaded', () => {
    initSidebar();
    initSidebarCollapse();
    initAlertDismiss();
    initFlashToasts();
    initDeleteConfirmation();
    initRowKeyboardFocus();
    initTypeaheadSelects();
    initStockByItemFilter();
    initFormsetControls();
    initStockCardSearch();
    initStockTransferTable();
    initTooltips();
    initDateMaskInputs();
    initDmyDateValidation();
});

/** Sidebar toggle for mobile */
function initSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    const toggleBtn = document.getElementById('sidebarToggleMobile');
    const closeBtn = document.getElementById('sidebarToggle');

    function openSidebar() {
        if (sidebar) sidebar.classList.add('show');
        if (overlay) overlay.classList.add('show');
    }

    function closeSidebar() {
        if (sidebar) sidebar.classList.remove('show');
        if (overlay) overlay.classList.remove('show');
    }

    if (toggleBtn) toggleBtn.addEventListener('click', openSidebar);
    if (closeBtn) closeBtn.addEventListener('click', closeSidebar);
    if (overlay) overlay.addEventListener('click', closeSidebar);
}

/** Enable keyboard focus on table rows for quicker navigation */
function initRowKeyboardFocus() {
    document.querySelectorAll('.table tbody tr').forEach((tr) => {
        tr.setAttribute('tabindex', '0');
        tr.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                const link = tr.querySelector('a');
                if (link) link.click();
            }
        });
    });
}

/** Typeahead select: input + suggestion list, selects option on click */
function initTypeaheadSelects() {
    document.querySelectorAll('select.js-typeahead-select').forEach((select) => {
        if (select.dataset.typeaheadInitialized === 'true') return;
        select.dataset.typeaheadInitialized = 'true';

        const wrapper = document.createElement('div');
        wrapper.className = 'typeahead-select';

        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control form-control-sm typeahead-input';
        input.placeholder = select.getAttribute('data-search-placeholder') || 'Cari barang...';
        input.setAttribute('autocomplete', 'off');
        input.setAttribute('aria-label', 'Cari barang');

        const dropdown = document.createElement('div');
        dropdown.className = 'typeahead-dropdown';
        dropdown.setAttribute('role', 'listbox');
        dropdown.setAttribute('aria-label', 'Hasil pencarian');

        const optionsSnapshot = Array.from(select.options).map((opt) => ({
            value: opt.value,
            text: opt.text,
            disabled: opt.disabled,
        }));

        const parent = select.parentNode;
        parent.insertBefore(wrapper, select);
        wrapper.appendChild(input);
        wrapper.appendChild(dropdown);
        wrapper.appendChild(select);

        select.style.display = 'none';

        const syncInputFromSelect = () => {
            const selectedOption = select.selectedOptions?.[0] || select.options[select.selectedIndex] || null;
            input.value = selectedOption && selectedOption.value ? selectedOption.text : '';
        };

        const renderOptions = (query) => {
            const q = (query || '').trim().toLowerCase();
            dropdown.innerHTML = '';
            if (!q) {
                dropdown.classList.remove('show');
                return;
            }

            const matches = optionsSnapshot.filter((opt) => {
                if (opt.value === '') return false;
                return opt.text.toLowerCase().includes(q);
            });

            if (matches.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'typeahead-item empty';
                empty.textContent = 'Tidak ada hasil';
                dropdown.appendChild(empty);
                dropdown.classList.add('show');
                return;
            }

            matches.slice(0, 10).forEach((opt, index) => {
                const item = document.createElement('button');
                item.type = 'button';
                item.className = 'typeahead-item';
                item.textContent = opt.text;
                item.setAttribute('role', 'option');
                item.dataset.value = opt.value;
                item.dataset.index = String(index);
                item.disabled = opt.disabled;
                item.addEventListener('click', () => {
                    select.value = opt.value;
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    dropdown.classList.remove('show');
                });
                dropdown.appendChild(item);
            });

            dropdown.classList.add('show');
        };

        const setActiveIndex = (idx) => {
            const items = Array.from(dropdown.querySelectorAll('.typeahead-item:not(.empty)'));
            items.forEach((el, i) => {
                el.classList.toggle('active', i === idx);
                if (i === idx) {
                    el.scrollIntoView({ block: 'nearest' });
                }
            });
            dropdown.dataset.activeIndex = String(idx);
        };

        const moveActive = (delta) => {
            const items = Array.from(dropdown.querySelectorAll('.typeahead-item:not(.empty)'));
            if (items.length === 0) return;
            const current = parseInt(dropdown.dataset.activeIndex || '-1', 10);
            let next = current + delta;
            if (next < 0) next = items.length - 1;
            if (next >= items.length) next = 0;
            setActiveIndex(next);
        };

        const chooseActive = () => {
            const items = Array.from(dropdown.querySelectorAll('.typeahead-item:not(.empty)'));
            if (items.length === 0) return;
            const current = parseInt(dropdown.dataset.activeIndex || '0', 10);
            const active = items[current] || items[0];
            active.click();
        };

        input.addEventListener('input', () => {
            renderOptions(input.value);
            setActiveIndex(0);
        });
        input.addEventListener('focus', () => {
            renderOptions(input.value);
            setActiveIndex(0);
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                dropdown.classList.remove('show');
                return;
            }
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                moveActive(1);
                return;
            }
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                moveActive(-1);
                return;
            }
            if (e.key === 'Enter') {
                if (dropdown.classList.contains('show')) {
                    e.preventDefault();
                    chooseActive();
                }
            }
        });

        document.addEventListener('click', (e) => {
            if (!wrapper.contains(e.target)) dropdown.classList.remove('show');
        });

        // If select changes programmatically, reflect in input
        select.addEventListener('change', () => {
            syncInputFromSelect();
        });

        syncInputFromSelect();
        window.setTimeout(syncInputFromSelect, 0);
    });
}

/** Add/remove rows for Django formsets */
function initFormsetControls() {
    document.querySelectorAll('[data-formset]').forEach((container) => {
        const prefix = container.getAttribute('data-formset-prefix');
        const totalInput = document.querySelector(`input[name="${prefix}-TOTAL_FORMS"]`);
        const emptyTemplate = document.getElementById(`${container.dataset.formset}-empty`);
        if (!prefix || !totalInput || !emptyTemplate) return;

        const tableBody = container.querySelector('tbody');
        if (!tableBody) return;

        const addButtons = document.querySelectorAll(`.formset-add[data-formset-target="${container.dataset.formset}"]`);
        addButtons.forEach((btn) => {
            btn.addEventListener('click', () => {
                const index = parseInt(totalInput.value, 10);
                const html = emptyTemplate.innerHTML.replace(/__prefix__/g, String(index));
                const wrapper = document.createElement('tbody');
                wrapper.innerHTML = html.trim();
                const row = wrapper.querySelector('tr');
                if (!row) return;
                tableBody.appendChild(row);
                totalInput.value = index + 1;
                initTypeaheadSelects();
                initStockByItemFilter();
            });
        });

        tableBody.addEventListener('click', (e) => {
            const btn = e.target.closest('.formset-remove');
            if (!btn) return;
            const row = btn.closest('tr');
            if (!row) return;
            const visibleRows = Array.from(tableBody.querySelectorAll('tr.formset-row')).filter(
                (r) => !r.classList.contains('d-none')
            );
            if (visibleRows.length <= 1) {
                return;
            }
            const deleteInput = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
            if (deleteInput) {
                deleteInput.checked = true;
                row.classList.add('d-none');
            } else {
                row.remove();
                const forms = tableBody.querySelectorAll('tr.formset-row');
                totalInput.value = forms.length;
            }
        });

        const clearButtons = document.querySelectorAll(`.formset-clear[data-formset-target="${container.dataset.formset}"]`);
        clearButtons.forEach((btn) => {
            btn.addEventListener('click', () => {
                if (!confirm('Hapus semua baris? Setidaknya satu baris akan tetap tersedia.')) {
                    return;
                }
                const rows = Array.from(tableBody.querySelectorAll('tr.formset-row'));
                if (rows.length === 0) return;
                rows.forEach((row, index) => {
                    if (index === 0) {
                        const deleteInput = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
                        if (deleteInput) deleteInput.checked = false;
                        row.classList.remove('d-none');
                        row.querySelectorAll('input, select, textarea').forEach((field) => {
                            if (field.type === 'checkbox' || field.type === 'radio') {
                                field.checked = false;
                            } else {
                                field.value = '';
                            }
                        });
                    } else {
                        const deleteInput = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
                        if (deleteInput) {
                            deleteInput.checked = true;
                            row.classList.add('d-none');
                        } else {
                            row.remove();
                        }
                    }
                });
                const remaining = tableBody.querySelectorAll('tr.formset-row').length;
                totalInput.value = remaining;
            });
        });
    });
}

/** Kartu stok: inline typeahead search with keyboard navigation */
function initStockCardSearch() {
    const searchInput = document.getElementById('itemSearch');
    const searchResults = document.getElementById('searchResults');
    if (!searchInput || !searchResults) return;

    const searchUrl = searchInput.getAttribute('data-search-url') || '/stock/api/item-search/';
    const detailTemplate = searchInput.getAttribute('data-detail-template') || '/stock/stock-card/0/';
    let debounceTimer = null;
    let activeIndex = -1;

    const buildDetailUrl = (id) => detailTemplate.replace(/0\/?$/, `${id}/`);

    const getResultItems = () => Array.from(searchResults.querySelectorAll('.search-result-item'));

    const setActiveIndex = (index) => {
        const items = getResultItems();
        items.forEach((el, i) => {
            el.classList.toggle('active', i === index);
            if (i === index) el.scrollIntoView({ block: 'nearest' });
        });
        activeIndex = index;
    };

    const resetActiveIndex = () => {
        activeIndex = -1;
        getResultItems().forEach((el) => el.classList.remove('active'));
    };

    const showNoResult = (message) => {
        searchResults.innerHTML = `<div class="p-3 text-center text-muted">${message}</div>`;
        searchResults.style.display = 'block';
        resetActiveIndex();
    };

    const renderResults = (results, query) => {
        searchResults.innerHTML = '';
        if (!results || results.length === 0) {
            showNoResult(`Tidak ada barang yang cocok dengan "${query}"`);
            return;
        }

        results.forEach((item) => {
            const text = item.text || '';
            const parts = text.split(' - ');
            const code = parts[0] || '';
            const name = parts.slice(1).join(' - ') || text;

            const a = document.createElement('a');
            a.href = buildDetailUrl(item.id);
            a.className = 'search-result-item';
            a.innerHTML = `
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <div class="fw-bold">${name}</div>
                        <div class="item-code">${code}</div>
                    </div>
                    <div class="text-end text-muted small">
                        <div><span class="badge bg-light text-dark border">${item.kategori || '-'}</span></div>
                        <div>Stok: ${item.stock ?? 0} ${item.satuan || ''}</div>
                    </div>
                </div>
            `;
            a.addEventListener('mouseenter', () => {
                const items = getResultItems();
                setActiveIndex(items.indexOf(a));
            });
            searchResults.appendChild(a);
        });

        searchResults.style.display = 'block';
        setActiveIndex(0);
    };

    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
            searchResults.style.display = 'none';
            resetActiveIndex();
        }
    });

    searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        const query = searchInput.value.trim();
        if (query.length < 2) {
            searchResults.style.display = 'none';
            resetActiveIndex();
            return;
        }

        debounceTimer = setTimeout(() => {
            const url = `${searchUrl}?q=${encodeURIComponent(query)}`;
            fetch(url)
                .then((response) => response.json())
                .then((data) => renderResults(data.results, query))
                .catch(() => showNoResult('Gagal memuat data barang.'));
        }, 300);
    });

    searchInput.addEventListener('focus', () => {
        if (searchInput.value.trim().length >= 2 && searchResults.innerHTML !== '') {
            searchResults.style.display = 'block';
            if (activeIndex < 0 && getResultItems().length > 0) setActiveIndex(0);
        }
    });

    searchInput.addEventListener('keydown', (e) => {
        const items = getResultItems();
        if (searchResults.style.display !== 'block' || items.length === 0) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            const nextIndex = activeIndex < items.length - 1 ? activeIndex + 1 : 0;
            setActiveIndex(nextIndex);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            const nextIndex = activeIndex > 0 ? activeIndex - 1 : items.length - 1;
            setActiveIndex(nextIndex);
        } else if (e.key === 'Enter') {
            if (activeIndex >= 0 && activeIndex < items.length) {
                e.preventDefault();
                window.location.href = items[activeIndex].href;
            }
        } else if (e.key === 'Escape') {
            searchResults.style.display = 'none';
            resetActiveIndex();
        }
    });
}

/** Filter stock(batch) options by selected item in the same row */
function initStockByItemFilter() {
    const bindRow = (row) => {
        if (!row || row.dataset.stockFilterInitialized === 'true') return;
        const itemSelect = row.querySelector('select.js-item-select');
        const stockSelect = row.querySelector('select.js-stock-select');
        if (!itemSelect || !stockSelect) return;

        row.dataset.stockFilterInitialized = 'true';

        const stockOptionsSnapshot = Array.from(stockSelect.options).map((opt) => ({
            value: opt.value,
            text: opt.text,
            itemId: opt.getAttribute('data-item-id') || '',
            selected: opt.selected,
            disabled: opt.disabled,
        }));

        const applyFilter = () => {
            const selectedItemId = itemSelect.value;
            const currentValue = stockSelect.value;
            const placeholder = stockOptionsSnapshot.find((opt) => opt.value === '');

            stockSelect.innerHTML = '';

            if (placeholder) {
                const placeholderOpt = new Option(placeholder.text, '', false, false);
                placeholderOpt.disabled = placeholder.disabled;
                stockSelect.appendChild(placeholderOpt);
            }

            if (!selectedItemId) {
                stockSelect.value = '';
                stockSelect.disabled = true;
                return;
            }

            const matched = stockOptionsSnapshot.filter(
                (opt) => opt.value && opt.itemId === selectedItemId
            );

            matched.forEach((opt) => {
                const optionEl = new Option(opt.text, opt.value, false, opt.value === currentValue);
                optionEl.disabled = opt.disabled;
                optionEl.setAttribute('data-item-id', opt.itemId);
                stockSelect.appendChild(optionEl);
            });

            if (!matched.some((opt) => opt.value === currentValue)) {
                stockSelect.value = '';
            }

            stockSelect.disabled = false;
        };

        itemSelect.addEventListener('change', applyFilter);
        applyFilter();
    };

    document.querySelectorAll('tr.formset-row').forEach(bindRow);
}

/** Sidebar collapse toggle for desktop */
function initSidebarCollapse() {
    const sidebar = document.getElementById('sidebar');
    const pageWrapper = document.getElementById('page-content-wrapper');
    const collapseBtn = document.getElementById('sidebarCollapseBtn');

    if (!sidebar || !collapseBtn) return;

    // Restore saved state
    if (localStorage.getItem('sidebarCollapsed') === 'true') {
        sidebar.classList.add('collapsed');
        if (pageWrapper) pageWrapper.classList.add('sidebar-collapsed');
    }

    collapseBtn.addEventListener('click', () => {
        const isCollapsed = sidebar.classList.toggle('collapsed');
        if (pageWrapper) pageWrapper.classList.toggle('sidebar-collapsed', isCollapsed);
        localStorage.setItem('sidebarCollapsed', isCollapsed);
        // Ensure any dropdown toggle that should be active keeps the active
        // appearance after collapsing/expanding. When collapsed the server-side
        // active class may be present on child links but not on the parent
        // toggle; this sync will add/remove `.active` on the toggle where
        // appropriate so the icon doesn't look dimmed.
        syncDropdownActiveStates(sidebar);
    });
}

function syncDropdownActiveStates(sidebar) {
    if (!sidebar) return;
    sidebar.querySelectorAll('.sidebar-dropdown-toggle').forEach(toggle => {
        const target = document.querySelector(toggle.getAttribute('data-bs-target'));
        if (!target) return;
        // If any child link is active or submenu is shown, mark the toggle active
        const shouldBeActive = target.querySelector('.sidebar-link.active') !== null || target.classList.contains('show');
        toggle.classList.toggle('active', shouldBeActive);
    });
}

// Run once on load to correct any mismatched active state
document.addEventListener('DOMContentLoaded', () => {
    syncDropdownActiveStates(document.getElementById('sidebar'));
});


/** Auto-dismiss alerts after 5 seconds */
function initAlertDismiss() {
    document.querySelectorAll('.alert-dismissible').forEach(alert => {
        setTimeout(() => {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 5000);
    });
}

/** Show Django flash messages as Bootstrap toasts */
function initFlashToasts() {
    const toasts = document.querySelectorAll('.flash-toast');
    if (toasts.length === 0) return;

    if (typeof bootstrap !== 'undefined' && bootstrap.Toast) {
        toasts.forEach((toastEl) => {
            const toast = bootstrap.Toast.getOrCreateInstance(toastEl);
            toast.show();
        });
        return;
    }

    toasts.forEach((toastEl) => {
        const delay = Number.parseInt(toastEl.getAttribute('data-bs-delay') || '4500', 10);
        setTimeout(() => {
            toastEl.classList.remove('show');
            toastEl.classList.add('hide');
            toastEl.addEventListener('transitionend', () => toastEl.remove(), { once: true });
        }, Number.isFinite(delay) ? delay : 4500);

        const closeBtn = toastEl.querySelector('[data-bs-dismiss="toast"]');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                toastEl.classList.remove('show');
                toastEl.classList.add('hide');
                setTimeout(() => toastEl.remove(), 180);
            });
        }
    });
}

/** Confirm before deleting */
function initDeleteConfirmation() {
    document.querySelectorAll('[data-confirm]').forEach(el => {
        el.addEventListener('click', (e) => {
            const message = el.getAttribute('data-confirm') || 'Apakah Anda yakin ingin menghapus?';
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });
}

/**
 * Utility: Format number to Indonesian locale
 */
function formatNumber(num) {
    const value = typeof num === 'string' ? Number.parseFloat(num) : num;
    if (!Number.isFinite(value)) return '0';
    return new Intl.NumberFormat('id-ID').format(value);
}

/**
 * Utility: Format decimal with Indonesian separators
 */
function formatDecimal(num, minFractionDigits = 2, maxFractionDigits = 2) {
    const value = typeof num === 'string' ? Number.parseFloat(num) : num;
    if (!Number.isFinite(value)) return '0';
    return new Intl.NumberFormat('id-ID', {
        minimumFractionDigits: minFractionDigits,
        maximumFractionDigits: maxFractionDigits,
    }).format(value);
}

/**
 * Utility: Format currency (IDR)
 */
function formatCurrency(num) {
    return new Intl.NumberFormat('id-ID', {
        style: 'currency',
        currency: 'IDR',
        minimumFractionDigits: 0,
    }).format(num);
}

/** Initialize Bootstrap tooltips */
function initTooltips() {
    if (typeof bootstrap === 'undefined' || !bootstrap.Tooltip) return;
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
        bootstrap.Tooltip.getOrCreateInstance(el);
    });
}

/** Stock transfer create page: location-indexed searchable stock table */
function initStockTransferTable() {
    const form = document.getElementById('transferForm');
    if (!form) return;

    const sourceLocation = form.querySelector('[name="source_location"]');
    const searchInput = document.getElementById('locationStockSearch');
    const tableBody = document.getElementById('locationStockTableBody');
    const searchUrl = form.getAttribute('data-stock-search-url');

    if (!sourceLocation || !searchInput || !tableBody || !searchUrl) return;

    let debounceTimer = null;

    const renderRows = (rows) => {
        tableBody.innerHTML = '';
        if (!rows || rows.length === 0) {
            const tr = document.createElement('tr');
            tr.innerHTML = '<td colspan="8" class="text-center text-muted py-3">Tidak ada stok yang cocok.</td>';
            tableBody.appendChild(tr);
            return;
        }

        rows.forEach((row) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><code>${row.kode}</code><input type="hidden" name="stock_id" value="${row.stock_id}"></td>
                <td>${row.nama}</td>
                <td><span class="badge bg-light text-dark border">${row.kategori || '-'}</span></td>
                <td>${row.batch}</td>
                <td>${row.expiry}</td>
                <td class="text-end fw-semibold">${formatDecimal(row.available)}</td>
                <td><span class="badge bg-light text-dark border">${row.funding}</span></td>
                <td>
                    <div class="input-group input-group-sm">
                        <input type="number" step="0.01" min="0" max="${row.available}" name="quantity" class="form-control form-control-sm" value="0" placeholder="0">
                        <button type="button" class="btn btn-outline-secondary js-fill-max" data-available="${row.available}" title="Isi Semua" data-bs-toggle="tooltip" data-bs-placement="top" data-bs-title="Isi Semua">
                            <i class="bi bi-arrow-bar-down"></i>
                        </button>
                    </div>
                </td>
            `;
            tableBody.appendChild(tr);
        });

        initTooltips();
    };

    tableBody.addEventListener('click', (e) => {
        const btn = e.target.closest('.js-fill-max');
        if (!btn) return;
        const row = btn.closest('tr');
        if (!row) return;
        const qtyInput = row.querySelector('input[name="quantity"]');
        if (!qtyInput) return;
        qtyInput.value = btn.getAttribute('data-available') || '0';
    });

    const fetchRows = () => {
        const location = sourceLocation.value;
        const query = searchInput.value.trim();

        if (!location) {
            tableBody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-3">Pilih lokasi asal untuk menampilkan stok.</td></tr>';
            return;
        }

        const url = `${searchUrl}?location=${encodeURIComponent(location)}&q=${encodeURIComponent(query)}`;
        fetch(url)
            .then((res) => res.json())
            .then((data) => renderRows(data.results || []))
            .catch(() => {
                tableBody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-3">Gagal memuat data stok.</td></tr>';
            });
    };

    sourceLocation.addEventListener('change', fetchRows);
    searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(fetchRows, 250);
    });

    fetchRows();
}

/** Simple dd/mm/yyyy mask for date text inputs */
function initDateMaskInputs() {
    const maskValue = (raw) => {
        const digits = (raw || '').replace(/\D/g, '').slice(0, 8);
        if (digits.length <= 2) return digits;
        if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
        return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
    };

    document.querySelectorAll('input.js-date-mask').forEach((input) => {
        if (input.dataset.maskInitialized === 'true') return;
        input.dataset.maskInitialized = 'true';

        input.addEventListener('input', () => {
            input.value = maskValue(input.value);
        });

        input.addEventListener('paste', (e) => {
            e.preventDefault();
            const text = (e.clipboardData || window.clipboardData).getData('text');
            input.value = maskValue(text);
        });
    });
}

/** Inline validation for dd/mm/yyyy date range filters */
function initDmyDateValidation() {
    document.querySelectorAll('form[data-date-validate="dmy"]').forEach((form) => {
        const fromInput = form.querySelector('input[name="date_from"]');
        const toInput = form.querySelector('input[name="date_to"]');
        const feedback = form.querySelector('#dateRangeFeedback');
        if (!fromInput || !toInput || !feedback) return;

        const parseDmy = (value) => {
            const v = (value || '').trim();
            if (!v) return null;
            const match = v.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
            if (!match) return { valid: false };
            const day = Number(match[1]);
            const month = Number(match[2]);
            const year = Number(match[3]);
            const dt = new Date(year, month - 1, day);
            const isValid =
                dt.getFullYear() === year &&
                dt.getMonth() === month - 1 &&
                dt.getDate() === day;
            return isValid ? { valid: true, date: dt } : { valid: false };
        };

        const setError = (message) => {
            feedback.textContent = message;
            feedback.classList.remove('d-none');
            fromInput.classList.add('is-invalid');
            toInput.classList.add('is-invalid');
        };

        const clearError = () => {
            feedback.textContent = '';
            feedback.classList.add('d-none');
            fromInput.classList.remove('is-invalid');
            toInput.classList.remove('is-invalid');
        };

        const validate = () => {
            const from = parseDmy(fromInput.value);
            const to = parseDmy(toInput.value);

            if (from && from.valid === false) {
                setError('Format Tanggal Dari harus DD/MM/YYYY yang valid.');
                return false;
            }
            if (to && to.valid === false) {
                setError('Format Tanggal Sampai harus DD/MM/YYYY yang valid.');
                return false;
            }
            if (from && to && from.valid && to.valid && from.date > to.date) {
                setError('Tanggal Dari tidak boleh lebih besar dari Tanggal Sampai.');
                return false;
            }

            clearError();
            return true;
        };

        fromInput.addEventListener('input', validate);
        toInput.addEventListener('input', validate);
        form.addEventListener('submit', (e) => {
            if (!validate()) {
                e.preventDefault();
            }
        });
    });
}
