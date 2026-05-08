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
    var strengthBar = document.getElementById('strengthBar');
    var strengthLabel = document.getElementById('strengthLabel');

    function updateStrength(val) {
        if (!strengthBar || !strengthLabel) return;
        var met = 0;
        var reqsLocal = {
            length: /.{10,}/,
            upper: /[A-Z]/,
            lower: /[a-z]/,
            number: /\d/,
            special: /[!@#$%^&*(),.?":{}|<>_+\-=\[\]\\;'/`~]/
        };
        for (var k in reqsLocal) {
            if (reqsLocal[k].test(val)) met++;
        }
        strengthBar.className = 'strength-bar';
        if (met <= 1) { strengthBar.classList.add('weak'); strengthLabel.textContent = 'Lemah'; }
        else if (met === 2 || met === 3) { strengthBar.classList.add('fair'); strengthLabel.textContent = 'Cukup'; }
        else if (met === 4) { strengthBar.classList.add('good'); strengthLabel.textContent = 'Baik'; }
        else { strengthBar.classList.add('strong'); strengthLabel.textContent = 'Kuat'; }
    }

    function getSecureRandomInt(max) {
        if (!window.crypto || !window.crypto.getRandomValues || max <= 0) {
            throw new Error('Secure random generator unavailable');
        }

        var values = new Uint32Array(1);
        var limit = Math.floor(4294967296 / max) * max;
        var randomNumber = 0;
        do {
            window.crypto.getRandomValues(values);
            randomNumber = values[0];
        } while (randomNumber >= limit);
        return randomNumber % max;
    }

    function generateSecurePassword(length) {
        var requiredGroups = [
            'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
            'abcdefghijklmnopqrstuvwxyz',
            '0123456789',
            '!@#$%^&*()_+-=[]{}|;:,.<>?'
        ];
        var allChars = requiredGroups.join('');
        var passwordChars = [];

        requiredGroups.forEach(function (group) {
            passwordChars.push(group.charAt(getSecureRandomInt(group.length)));
        });

        for (var i = passwordChars.length; i < length; i++) {
            passwordChars.push(allChars.charAt(getSecureRandomInt(allChars.length)));
        }

        for (var j = passwordChars.length - 1; j > 0; j--) {
            var swapIndex = getSecureRandomInt(j + 1);
            var currentChar = passwordChars[j];
            passwordChars[j] = passwordChars[swapIndex];
            passwordChars[swapIndex] = currentChar;
        }

        return passwordChars.join('');
    }

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
            updateStrength(val);
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

    // ── Generate Password ───────────────────────────────────────────
    var genBtn = document.getElementById('generatePasswordBtn');
    if (genBtn && pwdInput) {
        genBtn.addEventListener('click', function () {
            var pwd = '';
            try {
                pwd = generateSecurePassword(16);
            } catch (error) {
                window.alert('Browser tidak mendukung generator password aman.');
                return;
            }
            pwdInput.value = pwd;
            pwdInput.dispatchEvent(new Event('input'));
            pwdInput.focus();

            var pwd2 = document.getElementById('id_password2');
            if (pwd2) pwd2.value = pwd;

            if (pwdReqBox) pwdReqBox.classList.remove('d-none');

            navigator.clipboard.writeText(pwd).then(function () {
                var toast = document.createElement('div');
                toast.className = 'toast align-items-center text-bg-success border-0 position-fixed bottom-0 end-0 m-3';
                toast.setAttribute('role', 'alert');
                toast.innerHTML = '<div class="d-flex"><div class="toast-body">Password disalin!</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
                document.body.appendChild(toast);
                var bsToast = new bootstrap.Toast(toast, { delay: 2000 });
                bsToast.show();
                toast.addEventListener('hidden.bs.toast', function () { toast.remove(); });
            }).catch(function () {});
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
    document.querySelectorAll('.scope-segment input[type="radio"]').forEach(function (radio) {
        radio.addEventListener('change', function () {
            var segment = this.closest('.scope-segment');
            if (!segment) return;
            var parent = segment.parentElement;
            parent.querySelectorAll('.scope-segment').forEach(function (s) {
                s.classList.remove('active');
            });
            segment.classList.add('active');
            updateDeviationDots();
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

    // ── Keyboard shortcut: Esc to go back to user list ──────────────
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !e.target.closest('.modal') && !e.target.closest('input,textarea,select')) {
            var backLink = document.querySelector('.navbar-left-tools a[href*="/users/"]') ||
                           document.querySelector('a[href*="/users/"]');
            if (backLink) {
                e.preventDefault();
                window.location.href = backLink.href;
            }
        }
    });
});
