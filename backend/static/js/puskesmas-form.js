document.addEventListener("DOMContentLoaded", function () {
    initializeReceivingPreview();
    initializeLegacyReceivingFormset();
    initializeReceiptChecklist();
});

function initializeReceivingPreview() {
    var previewBtn = document.getElementById("preview-distribution-btn");
    var previewForm = document.getElementById("distribution-preview-form");
    var previewInput = document.getElementById("distribution-preview-input");
    var requestForm = document.getElementById("request-form");
    var distributionSelect = document.getElementById("id_distribution");

    if (!requestForm) return;

    var draftStorageKey = "puskesmas-receiving-preview:" + window.location.pathname;
    restoreReceivingPreviewDraft(draftStorageKey);

    if (!previewBtn || !previewForm || !previewInput || !distributionSelect) return;

    previewBtn.addEventListener("click", function () {
        if (!distributionSelect.value) {
            distributionSelect.focus();
            return;
        }

        persistReceivingPreviewDraft(draftStorageKey);
        previewInput.value = distributionSelect.value;
        previewForm.submit();
    });
}

function persistReceivingPreviewDraft(storageKey) {
    if (!window.sessionStorage) return;

    var draft = {};
    ["id_notes"].forEach(function (fieldId) {
        var field = document.getElementById(fieldId);
        if (field) {
            draft[fieldId] = field.value;
        }
    });

    try {
        window.sessionStorage.setItem(storageKey, JSON.stringify(draft));
    } catch (error) {
        // Ignore storage failures and continue with preview.
    }
}

function restoreReceivingPreviewDraft(storageKey) {
    if (!window.sessionStorage) return;

    var rawDraft = null;
    try {
        rawDraft = window.sessionStorage.getItem(storageKey);
    } catch (error) {
        return;
    }

    if (!rawDraft) return;

    try {
        var draft = JSON.parse(rawDraft);
        Object.keys(draft).forEach(function (fieldId) {
            var field = document.getElementById(fieldId);
            if (field && !field.value) {
                field.value = draft[fieldId];
            }
        });
    } catch (error) {
        // Ignore malformed preview drafts.
    }

    try {
        window.sessionStorage.removeItem(storageKey);
    } catch (error) {
        // Ignore storage cleanup failures.
    }
}

function initializeLegacyReceivingFormset() {
    var requestForm = document.getElementById("request-form");
    if (!requestForm || requestForm.dataset.receiptMode !== "legacy") return;

    var totalFormsInput = document.getElementById("id_items-TOTAL_FORMS");
    var formsetBody = document.getElementById("formset-body");
    var template = document.getElementById("empty-form-template");
    var addBtn = document.getElementById("add-item-btn");

    if (!totalFormsInput || !formsetBody || !template || !addBtn) return;

    addBtn.addEventListener("click", function () {
        var idx = parseInt(totalFormsInput.value, 10);
        var clone = template.content.cloneNode(true);

        clone.querySelectorAll("[name]").forEach(function (el) {
            el.name = el.name.replace("__prefix__", idx);
            el.id = el.id.replace("__prefix__", idx);
        });
        formsetBody.appendChild(clone);
        totalFormsInput.value = idx + 1;
    });

    formsetBody.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-action-remove-row]");
        if (!btn) return;
        removeLegacyRow(btn);
    });
}

function initializeReceiptChecklist() {
    var requestForm = document.getElementById("request-form");
    if (!requestForm || requestForm.dataset.receiptMode !== "checklist") return;

    var checkboxes = Array.prototype.slice.call(
        document.querySelectorAll(".receipt-line-checkbox")
    );
    if (!checkboxes.length) return;

    var countNode = document.getElementById("receipt-checklist-count");
    var badgeNode = document.getElementById("receipt-checklist-badge");
    var notesCard = document.getElementById("discrepancy-note-card");
    var noteHelp = document.getElementById("discrepancy-note-help");
    var draftChip = document.getElementById("draft-status-chip");

    function updateChecklistState() {
        var checkedCount = 0;

        checkboxes.forEach(function (checkbox) {
            var row = checkbox.closest("[data-checklist-row]");
            if (checkbox.checked) {
                checkedCount += 1;
                if (row) row.classList.add("receipt-row-checked");
            } else if (row) {
                row.classList.remove("receipt-row-checked");
            }
        });

        var totalCount = checkboxes.length;
        var summaryText = checkedCount + " / " + totalCount;

        if (countNode) {
            countNode.textContent = summaryText + " baris sesuai";
        }
        if (badgeNode) {
            badgeNode.textContent = summaryText + " sesuai";
        }
        if (notesCard) {
            notesCard.style.display = checkedCount === totalCount ? "none" : "";
        }
        if (noteHelp) {
            noteHelp.textContent =
                checkedCount === totalCount
                    ? "Semua baris sudah sesuai. Anda dapat menyimpan konfirmasi final."
                    : "Barang belum lengkap. Simpan sebagai draft agar status belum selesai terlihat jelas.";
        }
        if (draftChip) {
            draftChip.style.display = checkedCount === totalCount ? "none" : "inline-flex";
        }
    }

    checkboxes.forEach(function (checkbox) {
        checkbox.addEventListener("change", updateChecklistState);
        checkbox.addEventListener("click", updateChecklistState);
    });

    updateChecklistState();
}

function removeLegacyRow(btn) {
    var row = btn.closest("tr");
    if (!row) return;

    var deleteInput = row.querySelector("input[type=checkbox][name$='-DELETE']");
    if (deleteInput) {
        deleteInput.checked = true;
        row.style.display = "none";
    } else {
        row.remove();
        renumberLegacyForms();
    }
}

function renumberLegacyForms() {
    var formsetBody = document.getElementById("formset-body");
    if (!formsetBody) return;
    var totalFormsInput = document.getElementById("id_items-TOTAL_FORMS");
    var rows = formsetBody.querySelectorAll("tr.formset-row:not([style*='display: none'])");
    rows.forEach(function (row, idx) {
        row.querySelectorAll("[name]").forEach(function (el) {
            el.name = el.name.replace(/items-\d+-/, "items-" + idx + "-");
            el.id = el.id.replace(/items-\d+-/, "items-" + idx + "-");
        });
    });
    if (totalFormsInput) totalFormsInput.value = rows.length;
}
