document.addEventListener('DOMContentLoaded', function () {
    var settingsCard = document.getElementById('numbering-settings-card');
    if (!settingsCard) {
        return;
    }

    var year = settingsCard.getAttribute('data-preview-year') || String(new Date().getFullYear());
    var month = settingsCard.getAttribute('data-preview-month') || '01';
    var parent = settingsCard.getAttribute('data-preview-parent') || 'SPJ-2026-00001';

    document.querySelectorAll('[data-numbering-rule]').forEach(function (row) {
        var templateInput = row.querySelector('input[name$="-template"]');
        var paddingInput = row.querySelector('input[name$="-padding"]');
        var preview = row.querySelector('[data-numbering-preview]');
        if (!templateInput || !paddingInput || !preview) return;

        function syncPreview() {
            var padding = Math.max(1, Number.parseInt(paddingInput.value || '1', 10));
            var sequence = '12'.padStart(padding, '0');
            preview.textContent = (templateInput.value || '')
                .replaceAll('{seq}', sequence)
                .replaceAll('{year}', year)
                .replaceAll('{month}', month)
                .replaceAll('{parent}', parent);
        }
        templateInput.addEventListener('input', syncPreview);
        paddingInput.addEventListener('input', syncPreview);
        syncPreview();
    });
});
