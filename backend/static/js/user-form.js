/**
 * User form: tabs, password visibility, strength requirements,
 * dynamic UAC pre-selection, and tab error badges.
 */
document.addEventListener('DOMContentLoaded', function () {
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.forEach(function (el) {
        new bootstrap.Tooltip(el);
    });

    // ── Tab error badge counting ──────────────────────────────────
    function updateTabErrors() {
        var profilPane = document.getElementById('profilPane');
        var aksesPane = document.getElementById('aksesPane');
        var profilCount = document.getElementById('profilErrorCount');
        var aksesCount = document.getElementById('aksesErrorCount');

        if (profilPane && profilCount) {
            var profilErrors = profilPane.querySelectorAll('.invalid-feedback.d-block').length;
            if (profilErrors > 0) {
                profilCount.textContent = profilErrors;
                profilCount.classList.remove('d-none');
            } else {
                profilCount.classList.add('d-none');
            }
        }

        if (aksesPane && aksesCount) {
            var aksesErrors = aksesPane.querySelectorAll('.invalid-feedback.d-block').length;
            if (aksesErrors > 0) {
                aksesCount.textContent = aksesErrors;
                aksesCount.classList.remove('d-none');
            } else {
                aksesCount.classList.add('d-none');
            }
        }
    }

    updateTabErrors();

    // ── Password Visibility Toggle ──────────────────────────────────
    document.querySelectorAll('.toggle-password').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var input = this.previousElementSibling;
            var icon = this.querySelector('i');
            if (input.type === 'password') {
                input.type = 'text';
                icon.classList.remove('bi-eye-slash');
                icon.classList.add('bi-eye');
            } else {
                input.type = 'password';
                icon.classList.remove('bi-eye');
                icon.classList.add('bi-eye-slash');
            }
        });
    });

    // ── Password Requirements Tracking ──────────────────────────────
    var pwdInput = document.getElementById('id_password1');
    var pwdReqBox = document.getElementById('password-requirements');
    if (pwdInput && pwdReqBox) {
        pwdInput.addEventListener('focus', function() {
            pwdReqBox.classList.remove('d-none');
        });

        var reqs = {
            length: { el: document.getElementById('req-length'), regex: /.{10,}/ },
            upper: { el: document.getElementById('req-upper'), regex: /[A-Z]/ },
            lower: { el: document.getElementById('req-lower'), regex: /[a-z]/ },
            number: { el: document.getElementById('req-number'), regex: /\d/ },
            special: { el: document.getElementById('req-special'), regex: /[!@#$%^&*(),.?":{}|<>_+\-=\[\]\\;'/`~]/ }
        };

        pwdInput.addEventListener('input', function() {
            var val = this.value;
            for (var key in reqs) {
                var req = reqs[key];
                var icon = req.el.querySelector('i');
                if (req.regex.test(val)) {
                    icon.className = 'bi bi-check text-success fw-bold me-1';
                    req.el.classList.replace('text-muted', 'text-success');
                } else {
                    icon.className = 'bi bi-x text-danger fw-bold me-1';
                    req.el.classList.replace('text-success', 'text-muted');
                }
            }
        });
    }

    // ── Dynamic UAC pre-selection on Jabatan change ─────────────────
    var dataEl = document.getElementById('role-defaults-data');
    if (!dataEl) return;
    var roleDefaults = JSON.parse(dataEl.textContent);
    var roleSelect = document.getElementById('id_role');
    if (!roleSelect) return;
    var facilitySelect = document.getElementById('id_facility');
    var facilityGroup = facilitySelect ? facilitySelect.closest('.mb-3') : null;

    function syncFacilityField() {
        if (!facilityGroup || !facilitySelect) return;

        var isPuskesmas = roleSelect.value === 'PUSKESMAS';
        facilityGroup.classList.toggle('d-none', !isPuskesmas);
        facilitySelect.required = isPuskesmas;

        if (!isPuskesmas) {
            facilitySelect.value = '';
        }
    }

    function getDefaultScope(moduleCode) {
        if (!roleDefaults || !roleSelect) return null;
        var defaults = roleDefaults[roleSelect.value];
        return defaults ? defaults[moduleCode] : null;
    }

    function updateDeviationDots() {
        document.querySelectorAll('.uac-scope-row').forEach(function (row) {
            var moduleCode = row.getAttribute('data-module');
            var defaultScope = getDefaultScope(moduleCode);
            var dot = row.querySelector('.scope-deviation-dot');
            if (!dot) return;

            var checkedRadio = row.querySelector('input[type="radio"]:checked');
            var currentValue = checkedRadio ? parseInt(checkedRadio.value, 10) : null;

            if (defaultScope !== null && currentValue !== null && currentValue !== defaultScope) {
                dot.classList.remove('d-none');
            } else {
                dot.classList.add('d-none');
            }
        });
    }

    roleSelect.addEventListener('change', function () {
        var selectedRole = this.value;
        var defaults = roleDefaults[selectedRole];
        syncFacilityField();
        if (!defaults) return;

        for (var moduleName in defaults) {
            var scopeValue = defaults[moduleName];
            var radioName = 'module_scope__' + moduleName;
            var radio = document.querySelector(
                'input[type="radio"][name="' + radioName + '"][value="' + scopeValue + '"]'
            );
            if (radio) {
                radio.checked = true;
                var segment = radio.closest('.scope-segment');
                if (segment) {
                    var parent = segment.parentElement;
                    parent.querySelectorAll('.scope-segment').forEach(function (s) {
                        s.classList.remove('active');
                    });
                    segment.classList.add('active');
                }
            }
        }
        updateDeviationDots();
    });

    // ── Segmented control click handling ───────────────────────────
    document.querySelectorAll('.scope-segment').forEach(function (segment) {
        segment.addEventListener('click', function () {
            var radio = this.querySelector('input[type="radio"]');
            if (radio) {
                radio.checked = true;
                var parent = this.parentElement;
                parent.querySelectorAll('.scope-segment').forEach(function (s) {
                    s.classList.remove('active');
                });
                this.classList.add('active');
                updateDeviationDots();
            }
        });
    });

    // ── Reset to default scope button ─────────────────────────────
    var resetBtn = document.getElementById('resetScopeBtn');
    if (resetBtn) {
        resetBtn.addEventListener('click', function () {
            var defaults = roleDefaults[roleSelect.value];
            if (!defaults) return;

            if (!confirm('Reset semua scope ke default jabatan "' + roleSelect.options[roleSelect.selectedIndex].text + '"?')) {
                return;
            }

            for (var moduleName in defaults) {
                var scopeValue = defaults[moduleName];
                var radio = document.querySelector(
                    'input[type="radio"][name="module_scope__' + moduleName + '"][value="' + scopeValue + '"]'
                );
                if (radio) {
                    radio.checked = true;
                    var segment = radio.closest('.scope-segment');
                    if (segment) {
                        var parent = segment.parentElement;
                        parent.querySelectorAll('.scope-segment').forEach(function (s) {
                            s.classList.remove('active');
                        });
                        segment.classList.add('active');
                    }
                }
            }
            updateDeviationDots();
        });
    }

    syncFacilityField();
    updateDeviationDots();
});
