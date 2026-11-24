document.addEventListener('DOMContentLoaded', function () {
    const button = document.getElementById('add-expiry-line');
    const total = document.getElementById('id_form-TOTAL_FORMS');
    const template = document.getElementById('expiry-empty-line');
    if (!button || !total || !template) return;
    button.addEventListener('click', function () {
        const index = Number(total.value);
        if (index >= 100) return;
        const content = template.innerHTML.replaceAll('__prefix__', String(index));
        document.getElementById('expiry-lines').insertAdjacentHTML('beforeend', content);
        total.value = index + 1;
        initTypeaheadSelects();
        initStockByItemFilter();
    });
});
