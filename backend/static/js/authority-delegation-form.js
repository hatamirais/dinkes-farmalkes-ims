(function () {
    "use strict";

    const pickerInstances = new Map();
    if (window.flatpickr) {
        document
            .querySelectorAll('[data-datetime-picker="24h"]')
            .forEach(function (input) {
                const instance = window.flatpickr(input, {
                    allowInput: true,
                    altFormat: "d/m/Y H:i",
                    altInput: true,
                    altInputClass:
                        "form-control datetimeinput delegation-datetime-display",
                    dateFormat: "Y-m-d\\TH:i",
                    disableMobile: true,
                    enableTime: true,
                    locale:
                        (window.flatpickr.l10ns && window.flatpickr.l10ns.id) ||
                        "default",
                    minuteIncrement: 1,
                    time_24hr: true,
                });
                if (instance.altInput) {
                    instance.altInput.placeholder = "DD/MM/YYYY HH:mm";
                }
                pickerInstances.set(input.id, instance);
            });
    }

    const modeInputs = document.querySelectorAll('input[name="duration_mode"]');
    const endsAtInput = document.getElementById("id_ends_at");
    if (!modeInputs.length || !endsAtInput) return;

    const endsAtField =
        endsAtInput.closest("#div_id_ends_at") || endsAtInput.parentElement;

    function syncDurationFields() {
        const selected = document.querySelector(
            'input[name="duration_mode"]:checked'
        );
        const untilRevoked = selected && selected.value === "UNTIL_REVOKED";
        const endsAtPicker = pickerInstances.get(endsAtInput.id);

        endsAtInput.disabled = untilRevoked;
        endsAtInput.required = !untilRevoked;
        if (endsAtPicker && endsAtPicker.altInput) {
            endsAtPicker.altInput.disabled = untilRevoked;
        }
        if (untilRevoked) {
            if (endsAtPicker) {
                endsAtPicker.clear(false);
            } else {
                endsAtInput.value = "";
            }
        }
        endsAtField.hidden = untilRevoked;
        endsAtField.setAttribute("aria-hidden", untilRevoked ? "true" : "false");
    }

    modeInputs.forEach(function (input) {
        input.addEventListener("change", syncDurationFields);
    });
    syncDurationFields();
})();
