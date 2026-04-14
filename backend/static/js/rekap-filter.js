/**
 * Rekap report: sumber dana modal filter with select-all and apply logic
 */
document.addEventListener('DOMContentLoaded', function() {
    var selectAllCheckbox = document.getElementById('sdSelectAll');
    var sdCheckboxes = document.querySelectorAll('.sd-checkbox');
    var applyBtn = document.getElementById('applySumberDana');
    var filterForm = document.getElementById('rekapFilterForm');
    var hiddenInputsContainer = document.getElementById('sdHiddenInputs');

    if (!selectAllCheckbox || !applyBtn || !filterForm || !hiddenInputsContainer) return;

    // Initialize "select all" state
    function updateSelectAll() {
        var allChecked = sdCheckboxes.length > 0 && 
            Array.from(sdCheckboxes).every(function(cb) { return cb.checked; });
        var someChecked = Array.from(sdCheckboxes).some(function(cb) { return cb.checked; });
        selectAllCheckbox.checked = allChecked;
        selectAllCheckbox.indeterminate = someChecked && !allChecked;
    }
    updateSelectAll();

    // Toggle all
    selectAllCheckbox.addEventListener('change', function() {
        var checked = this.checked;
        sdCheckboxes.forEach(function(cb) { cb.checked = checked; });
    });

    // Individual checkbox change
    sdCheckboxes.forEach(function(cb) {
        cb.addEventListener('change', updateSelectAll);
    });

    // Apply button: update hidden inputs and submit form
    applyBtn.addEventListener('click', function() {
        // Clear existing hidden inputs
        hiddenInputsContainer.innerHTML = '';

        // Add selected sumber_dana as hidden inputs
        sdCheckboxes.forEach(function(cb) {
            if (cb.checked) {
                var input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'sumber_dana';
                input.value = cb.value;
                hiddenInputsContainer.appendChild(input);
            }
        });

        // Close modal and submit form
        var modal = bootstrap.Modal.getInstance(document.getElementById('sumberDanaModal'));
        modal.hide();
        filterForm.submit();
    });
});
