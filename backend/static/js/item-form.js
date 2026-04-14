/**
 * Item form: TomSelect initialization, program toggle, and quick-create AJAX modals
 *
 * Expected data attributes on the form container (#item-form-container):
 *   data-url-unit     – quick create unit URL
 *   data-url-category – quick create category URL
 *   data-url-program  – quick create program URL
 */
document.addEventListener('DOMContentLoaded', function () {
    var checkbox = document.getElementById('id_is_program_item');
    var programSelect = document.getElementById('id_program');
    var programField = programSelect ? programSelect.closest('.mb-3') : null;

    function initTomSelect(selectId, placeholder, isRequired) {
        var select = document.getElementById(selectId);
        if (!select || typeof TomSelect === 'undefined') return null;
        if (isRequired && !select.value) select.selectedIndex = -1;
        return new TomSelect(select, {
            create: false,
            allowEmptyOption: !isRequired,
            maxOptions: 500,
            placeholder: placeholder,
            searchField: ['text'],
            sortField: [{ field: '$score' }, { field: 'text' }],
        });
    }

    function toggleProgramField() {
        if (programField) programField.style.display = checkbox && checkbox.checked ? 'block' : 'none';
        if (programSelect) {
            if (checkbox && checkbox.checked) { programSelect.required = true; }
            else {
                programSelect.required = false;
                if (programTom) programTom.clear(true);
                else programSelect.value = '';
            }
        }
    }

    var satuanTom = initTomSelect('id_satuan', 'Pilih atau cari satuan...', true);
    var kategoriTom = initTomSelect('id_kategori', 'Pilih atau cari kategori...', true);
    var programTom = initTomSelect('id_program', 'Pilih atau cari program...');

    if (checkbox) {
        checkbox.addEventListener('change', toggleProgramField);
        toggleProgramField();
    }

    // AJAX helpers
    function getCookie(name) {
        var val = null;
        document.cookie.split(';').forEach(function (c) {
            c = c.trim();
            if (c.startsWith(name + '=')) val = decodeURIComponent(c.substring(name.length + 1));
        });
        return val;
    }

    function quickCreate(url, bodyStr, errorElId, modalId, tomInstance, fieldIds) {
        var errorEl = document.getElementById(errorElId);
        errorEl.classList.add('d-none');
        fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': getCookie('csrftoken')},
            body: bodyStr,
        })
        .then(function (r) { return r.json().then(function (data) { return {ok: r.ok, data: data}; }); })
        .then(function(result) {
            if (!result.ok) { errorEl.textContent = result.data.error; errorEl.classList.remove('d-none'); return; }
            if (tomInstance) {
                tomInstance.addOption({value: String(result.data.id), text: result.data.text});
                tomInstance.setValue(String(result.data.id));
            }
            fieldIds.forEach(function (id) {
                var el = document.getElementById(id);
                if (el) el.value = '';
            });
            bootstrap.Modal.getInstance(document.getElementById(modalId)).hide();
        });
    }

    // Read URLs from data attributes on the container
    var container = document.getElementById('item-form-container');
    var urlUnit = container ? container.getAttribute('data-url-unit') : '';
    var urlCategory = container ? container.getAttribute('data-url-category') : '';
    var urlProgram = container ? container.getAttribute('data-url-program') : '';

    // Tambah Satuan
    var btnSaveUnit = document.getElementById('btn-save-unit');
    if (btnSaveUnit) {
        btnSaveUnit.addEventListener('click', function() {
            var ids = ['unit-code', 'unit-name', 'unit-description'];
            var body = 'code=' + encodeURIComponent(document.getElementById('unit-code').value.trim())
                + '&name=' + encodeURIComponent(document.getElementById('unit-name').value.trim())
                + '&description=' + encodeURIComponent(document.getElementById('unit-description').value.trim());
            quickCreate(urlUnit, body, 'unit-error', 'modal-satuan', satuanTom, ids);
        });
    }

    // Tambah Kategori
    var btnSaveCat = document.getElementById('btn-save-cat');
    if (btnSaveCat) {
        btnSaveCat.addEventListener('click', function() {
            var ids = ['cat-code', 'cat-name', 'cat-sort_order'];
            var body = 'code=' + encodeURIComponent(document.getElementById('cat-code').value.trim())
                + '&name=' + encodeURIComponent(document.getElementById('cat-name').value.trim())
                + '&sort_order=' + encodeURIComponent(document.getElementById('cat-sort_order').value.trim());
            quickCreate(urlCategory, body, 'cat-error', 'modal-kategori', kategoriTom, ids);
        });
    }

    // Tambah Program
    var btnSaveProg = document.getElementById('btn-save-prog');
    if (btnSaveProg) {
        btnSaveProg.addEventListener('click', function() {
            var ids = ['prog-code', 'prog-name', 'prog-description'];
            var body = 'code=' + encodeURIComponent(document.getElementById('prog-code').value.trim())
                + '&name=' + encodeURIComponent(document.getElementById('prog-name').value.trim())
                + '&description=' + encodeURIComponent(document.getElementById('prog-description').value.trim());
            quickCreate(urlProgram, body, 'prog-error', 'modal-program', programTom, ids);
        });
    }
});
