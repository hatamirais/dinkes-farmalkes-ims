/**
 * LPLPO edit: live recalculation of computed fields
 */
function recalcRow(row) {
    var getVal = function (sel) { return parseFloat(row.querySelector(sel)?.value) || 0; };

    // Get values from either input or hidden field
    var stockAwalInput = row.querySelector('[name*="stock_awal"]');
    var stockAwal = stockAwalInput ? parseFloat(stockAwalInput.value) || 0 : 0;
    var penerimaan = getVal('[name*="penerimaan"]');
    var pemakaian = getVal('[name*="pemakaian"]');
    var waktuKosong = getVal('[name*="waktu_kosong"]');

    var persediaan = stockAwal + penerimaan;
    var stockKeseluruhan = persediaan - pemakaian;
    var stockOptimum = stockKeseluruhan * 1.2;
    var jumlahKebutuhan = (stockKeseluruhan * 0.2) + waktuKosong;

    row.querySelector('.js-persediaan').textContent = persediaan.toFixed(2);
    row.querySelector('.js-stock-keseluruhan').textContent = stockKeseluruhan.toFixed(2);
    row.querySelector('.js-stock-optimum').textContent = stockOptimum.toFixed(2);
    row.querySelector('.js-jumlah-kebutuhan').textContent = jumlahKebutuhan.toFixed(2);
}

document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.lplpo-row').forEach(function (row) {
        row.querySelectorAll('input[type="number"]').forEach(function (input) {
            input.addEventListener('input', function () { recalcRow(row); });
        });
    });
});
