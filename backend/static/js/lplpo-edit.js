/**
 * LPLPO edit: live recalculation of computed fields
 */
function recalcRow(row) {
    var getVal = function (sel) { return parseFloat(row.querySelector(sel)?.value) || 0; };

    // Get values from either input or hidden field
    var stockAwalInput = row.querySelector('[name*="stock_awal"]');
    var stockAwal = stockAwalInput ? parseFloat(stockAwalInput.value) || 0 : 0;
    var penerimaan = getVal('[name*="penerimaan"]');
    var pembelianPuskesmas = getVal('[name*="pembelian_puskesmas"]');
    var pemakaian = getVal('[name*="pemakaian"]');
    var waktuKosong = getVal('[name*="waktu_kosong"]');

    var persediaan = stockAwal + penerimaan + pembelianPuskesmas;
    var stockKeseluruhan = persediaan - pemakaian;
    var stockOptimum = pemakaian * 1.2;
    var requiredReplenishment = Math.max(stockOptimum - stockKeseluruhan, 0);
    var jumlahKebutuhan = requiredReplenishment + waktuKosong;

    row.querySelector('.js-persediaan').textContent = persediaan.toFixed(0);
    row.querySelector('.js-stock-keseluruhan').textContent = stockKeseluruhan.toFixed(0);
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
