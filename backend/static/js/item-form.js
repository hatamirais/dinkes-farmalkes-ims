/**
 * Item form: TomSelect initialization, program toggle, and quick-create AJAX modals.
 */
document.addEventListener('DOMContentLoaded', function () {
    var checkbox = document.getElementById('id_is_program_item');
    var programSelect = document.getElementById('id_program');
    var programField = programSelect ? programSelect.closest('.mb-3') : null;

    function initTomSelect(selectId, placeholder, isRequired, config) {
        var select = document.getElementById(selectId);
        if (!select || typeof TomSelect === 'undefined') return null;
        if (isRequired && !select.value) select.selectedIndex = -1;
        return new TomSelect(select, Object.assign({
            create: false,
            allowEmptyOption: !isRequired,
            maxOptions: 500,
            placeholder: placeholder,
            searchField: ['text'],
            sortField: [{ field: '$score' }, { field: 'text' }],
        }, config || {}));
    }

    function toggleProgramField() {
        if (programField) programField.style.display = checkbox && checkbox.checked ? 'block' : 'none';
        if (programSelect) {
            if (checkbox && checkbox.checked) {
                programSelect.required = true;
            } else {
                programSelect.required = false;
                if (programTom) programTom.clear(true);
                else programSelect.value = '';
            }
        }
    }

    var satuanTom = initTomSelect('id_satuan', 'Pilih atau cari satuan...', true);
    var kategoriTom = initTomSelect('id_kategori', 'Pilih atau cari kategori...', true);
    var programTom = initTomSelect('id_program', 'Pilih atau cari program...');
    var therapeuticTom = initTomSelect('id_therapeutic_classes', 'Pilih atau cari terapi obat...', false, {
        plugins: ['remove_button'],
    });

    if (checkbox) {
        checkbox.addEventListener('change', toggleProgramField);
        toggleProgramField();
    }

    function getCookie(name) {
        var val = null;
        document.cookie.split(';').forEach(function (c) {
            c = c.trim();
            if (c.startsWith(name + '=')) val = decodeURIComponent(c.substring(name.length + 1));
        });
        return val;
    }

    function quickCreate(url, bodyStr, errorElId, modalId, tomInstance, fieldIds, options) {
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
                if (options && options.multiple) tomInstance.addItem(String(result.data.id));
                else tomInstance.setValue(String(result.data.id));
            }
            fieldIds.forEach(function (id) {
                var el = document.getElementById(id);
                if (el) el.value = '';
            });
            bootstrap.Modal.getInstance(document.getElementById(modalId)).hide();
        });
    }

    var container = document.getElementById('item-form-container');
    var urlUnit = container ? container.getAttribute('data-url-unit') : '';
    var urlCategory = container ? container.getAttribute('data-url-category') : '';
    var urlProgram = container ? container.getAttribute('data-url-program') : '';
    var urlTherapeuticClass = container ? container.getAttribute('data-url-therapeutic-class') : '';

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

    var btnSaveTherapeutic = document.getElementById('btn-save-therapeutic');
    if (btnSaveTherapeutic) {
        btnSaveTherapeutic.addEventListener('click', function() {
            var ids = ['therapeutic-code', 'therapeutic-name', 'therapeutic-description'];
            var body = 'code=' + encodeURIComponent(document.getElementById('therapeutic-code').value.trim())
                + '&name=' + encodeURIComponent(document.getElementById('therapeutic-name').value.trim())
                + '&description=' + encodeURIComponent(document.getElementById('therapeutic-description').value.trim());
            quickCreate(urlTherapeuticClass, body, 'therapeutic-error', 'modal-therapeutic-class', therapeuticTom, ids, {multiple: true});
        });
    }
});
