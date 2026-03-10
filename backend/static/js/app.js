/**
 * Healthcare IMS - Application JavaScript (Vanilla JS)
 */

document.addEventListener('DOMContentLoaded', () => {
    initSidebar();
    initSidebarCollapse();
    initAlertDismiss();
    initDeleteConfirmation();
    initRowKeyboardFocus();
    initTypeaheadSelects();
    initStockByItemFilter();
    initFormsetControls();
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
                    input.value = opt.text;
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
            const selected = optionsSnapshot.find((opt) => opt.value === select.value);
            input.value = selected ? selected.text : '';
        });
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
    return new Intl.NumberFormat('id-ID').format(num);
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
