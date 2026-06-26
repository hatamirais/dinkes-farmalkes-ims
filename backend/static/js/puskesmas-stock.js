(function () {
    const MONTH_FALLBACK = new Intl.NumberFormat('id-ID');

    function parseStockRows(root) {
        const dataNode = root.querySelector('#puskesmas-stock-rows');
        if (!dataNode) {
            return [];
        }
        try {
            return JSON.parse(dataNode.textContent);
        } catch (error) {
            console.error('Gagal membaca data stok puskesmas.', error);
            return [];
        }
    }

    function formatNumber(value) {
        return MONTH_FALLBACK.format(Number(value || 0));
    }

    function sanitizeCsvCell(value) {
        const text = String(value ?? '');
        if (text.startsWith("'")) {
            return text;
        }
        return /^[\s]*[=+\-@]/.test(text) ? `'${text}` : text;
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function getCategoryBadgeClass(categoryKey) {
        const normalizedKey = (categoryKey || '').toLowerCase();
        if (normalizedKey === 'bahan gigi') {
            return 'category-badge category-badge--bahan-gigi';
        }
        if (normalizedKey === 'tablet') {
            return 'category-badge category-badge--tablet';
        }
        if (normalizedKey === 'injeksi') {
            return 'category-badge category-badge--injeksi';
        }
        if (normalizedKey === 'bahan medis') {
            return 'category-badge category-badge--bahan-medis';
        }
        return 'category-badge category-badge--default';
    }

    function buildGroupedMarkup(rows) {
        if (!rows.length) {
            return '';
        }

        const grouped = new Map();
        rows.forEach((row) => {
            const facilityName = row.facility_name || '-';
            if (!grouped.has(facilityName)) {
                grouped.set(facilityName, []);
            }
            grouped.get(facilityName).push(row);
        });

        const fragments = [];
        grouped.forEach((items, facilityName) => {
            fragments.push(`
                <tr class="group-row">
                    <td colspan="8" class="py-3">
                        <div class="d-flex flex-column flex-lg-row justify-content-between align-items-lg-center gap-2">
                            <div class="fw-semibold">${escapeHtml(facilityName)}</div>
                            <div class="small text-muted">${formatNumber(items.length)} item pada snapshot aktif</div>
                        </div>
                    </td>
                </tr>
            `);

            items.forEach((row) => {
                fragments.push(`
                    <tr>
                        <td><code class="kode-barang">${escapeHtml(row.kode_barang)}</code></td>
                        <td>${escapeHtml(row.nama_barang)}</td>
                        <td><span class="${getCategoryBadgeClass(row.kategori_key)}">${escapeHtml(row.kategori)}</span></td>
                        <td>${escapeHtml(row.satuan)}</td>
                        <td class="text-end fw-semibold ${row.is_below_threshold ? 'stock-below-threshold' : ''}">${formatNumber(row.stock_current)}</td>
                        <td><span class="month-pill">${escapeHtml(row.base_month_label || row.base_month)}</span></td>
                        <td class="text-end">${formatNumber(row.receipt_adjustment)}</td>
                        <td class="text-end">${formatNumber(row.consumption_adjustment)}</td>
                    </tr>
                `);
            });
        });
        return fragments.join('');
    }

    function filterRows(rows, searchTerm, categoryKey) {
        const normalizedSearch = (searchTerm || '').trim().toLocaleLowerCase('id-ID');
        const normalizedCategory = (categoryKey || '').trim().toLocaleLowerCase('id-ID');
        return rows.filter((row) => {
            const matchesSearch = !normalizedSearch || [row.kode_barang, row.nama_barang]
                .some((value) => String(value || '').toLocaleLowerCase('id-ID').includes(normalizedSearch));
            const matchesCategory = !normalizedCategory || String(row.kategori_key || '').toLocaleLowerCase('id-ID') === normalizedCategory;
            return matchesSearch && matchesCategory;
        });
    }

    function updateStats(root, rows) {
        const visibleFacilities = new Set(rows.map((row) => row.facility_id)).size;
        const totalStock = rows.reduce((sum, row) => sum + Number(row.stock_current || 0), 0);
        const facilitiesNode = root.querySelector('[data-stat-facilities]');
        const itemsNode = root.querySelector('[data-stat-items]');
        const stockNode = root.querySelector('[data-stat-stock]');
        const toolbarCountNode = root.querySelector('[data-toolbar-count]');
        if (facilitiesNode) {
            facilitiesNode.textContent = formatNumber(visibleFacilities);
        }
        if (itemsNode) {
            itemsNode.textContent = formatNumber(rows.length);
        }
        if (stockNode) {
            stockNode.textContent = formatNumber(totalStock);
        }
        if (toolbarCountNode) {
            toolbarCountNode.textContent = formatNumber(rows.length);
        }
    }

    function renderState(root, state) {
        const filteredRows = filterRows(state.rows, state.searchTerm, state.categoryKey);
        const tbody = root.querySelector('#puskesmas-stock-table-body');
        const emptyState = root.querySelector('[data-empty-state]');
        if (!tbody) {
            return;
        }

        if (!filteredRows.length) {
            tbody.innerHTML = '';
            emptyState?.classList.remove('d-none');
        } else {
            tbody.innerHTML = buildGroupedMarkup(filteredRows);
            emptyState?.classList.add('d-none');
        }

        state.filteredRows = filteredRows;
        updateStats(root, filteredRows);
        const exportButton = root.querySelector('[data-export-button]');
        if (exportButton) {
            exportButton.disabled = filteredRows.length === 0;
        }
    }

    async function fetchAndSwapShell(url, submitButton) {
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.dataset.originalText = submitButton.innerHTML;
            submitButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Memuat';
        }

        try {
            const response = await fetch(url, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const html = await response.text();
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');
            const replacement = doc.querySelector('#puskesmas-stock-shell');
            const current = document.querySelector('#puskesmas-stock-shell');
            if (!replacement || !current) {
                window.location.assign(url);
                return;
            }
            current.outerHTML = replacement.outerHTML;
            window.history.replaceState({}, '', url);
            window.initPuskesmasStockPage();
        } catch (error) {
            console.error('Gagal memuat snapshot stok puskesmas.', error);
            window.location.assign(url);
        } finally {
            if (submitButton && submitButton.dataset.originalText) {
                submitButton.disabled = false;
                submitButton.innerHTML = submitButton.dataset.originalText;
            }
        }
    }

    function exportRows(rows, yearValue) {
        if (!rows.length) {
            return;
        }
        const headers = [
            'Puskesmas',
            'Kode Barang',
            'Nama Barang',
            'Kategori',
            'Satuan',
            'Stok Saat Ini',
            'Bulan LPLPO',
            'Penyesuaian Penerimaan',
            'Penyesuaian Pemakaian',
        ];
        const lines = [headers];
        rows.forEach((row) => {
            lines.push([
                row.facility_name,
                row.kode_barang,
                row.nama_barang,
                row.kategori,
                row.satuan,
                row.stock_current,
                row.base_month_label || row.base_month,
                row.receipt_adjustment,
                row.consumption_adjustment,
            ]);
        });
        const csv = lines.map((line) => line.map((value) => {
            const text = sanitizeCsvCell(value);
            return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
        }).join(',')).join('\r\n');
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `stok-puskesmas-${yearValue || 'snapshot'}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);
    }

    window.initPuskesmasStockPage = function initPuskesmasStockPage() {
        const root = document.querySelector('#puskesmas-stock-shell');
        if (!root) {
            return;
        }

        const state = {
            rows: parseStockRows(root),
            filteredRows: [],
            searchTerm: '',
            categoryKey: '',
        };

        const searchInput = root.querySelector('[data-stock-search]');
        const chipButtons = Array.from(root.querySelectorAll('[data-category-chip]'));
        const exportButton = root.querySelector('[data-export-button]');
        const inlineFilterForm = root.querySelector('[data-inline-filter-form]');
        const resetFilterLink = root.querySelector('[data-reset-filter]');

        if (searchInput) {
            searchInput.addEventListener('input', (event) => {
                state.searchTerm = event.target.value || '';
                renderState(root, state);
            });
        }

        chipButtons.forEach((button) => {
            button.addEventListener('click', () => {
                state.categoryKey = button.dataset.categoryChip || '';
                chipButtons.forEach((chip) => chip.classList.toggle('is-active', chip === button));
                renderState(root, state);
            });
        });

        if (exportButton) {
            exportButton.addEventListener('click', () => {
                const yearValue = root.querySelector('#id_year')?.value || '';
                exportRows(state.filteredRows, yearValue);
            });
        }

        if (inlineFilterForm) {
            inlineFilterForm.addEventListener('submit', (event) => {
                event.preventDefault();
                const submitButton = root.querySelector('[data-apply-filter]');
                const params = new URLSearchParams(new FormData(inlineFilterForm));
                const queryString = params.toString();
                const url = queryString ? `${inlineFilterForm.action}?${queryString}` : inlineFilterForm.action;
                fetchAndSwapShell(url, submitButton);
            });
        }

        if (resetFilterLink) {
            resetFilterLink.addEventListener('click', (event) => {
                event.preventDefault();
                fetchAndSwapShell(resetFilterLink.href);
            });
        }

        renderState(root, state);
    };

    document.addEventListener('DOMContentLoaded', window.initPuskesmasStockPage);
})();
