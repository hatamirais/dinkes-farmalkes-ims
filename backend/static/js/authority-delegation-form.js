(function () {
    "use strict";

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

        endsAtInput.disabled = untilRevoked;
        endsAtInput.required = !untilRevoked;
        if (untilRevoked) endsAtInput.value = "";
        endsAtField.hidden = untilRevoked;
        endsAtField.setAttribute("aria-hidden", untilRevoked ? "true" : "false");
    }

    modeInputs.forEach(function (input) {
        input.addEventListener("change", syncDurationFields);
    });
    syncDurationFields();
})();
