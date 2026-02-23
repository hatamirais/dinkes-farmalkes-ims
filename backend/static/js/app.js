/**
 * Healthcare IMS - Application JavaScript (Vanilla JS)
 */

document.addEventListener('DOMContentLoaded', () => {
    initSidebar();
    initAlertDismiss();
    initDeleteConfirmation();
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
