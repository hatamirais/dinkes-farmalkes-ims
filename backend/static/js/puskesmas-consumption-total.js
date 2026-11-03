document.addEventListener("DOMContentLoaded", function () {
    var matrix = document.querySelector(".ims-puskesmas-consumption-form .consumption-table");
    if (!matrix) return;

    var formatter = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });

    function updateRowTotal(row) {
        if (!row) return;
        var output = row.querySelector(".ims-consumption-total");
        if (!output) return;

        var total = 0;
        var inputs = row.querySelectorAll('input[name^="qty_"]');
        for (var input of inputs) {
            var raw = input.value.trim();
            if (!raw) continue;
            var quantity = Number(raw);
            if (!Number.isSafeInteger(quantity) || quantity < 0 || !Number.isSafeInteger(total + quantity)) {
                output.textContent = "—";
                return;
            }
            total += quantity;
        }
        output.textContent = formatter.format(total);
    }

    matrix.querySelectorAll(".ims-consumption-item-row").forEach(updateRowTotal);
    matrix.addEventListener("input", function (event) {
        if (!event.target.matches('input[name^="qty_"]')) return;
        updateRowTotal(event.target.closest(".ims-consumption-item-row"));
    });
});
