/**
 * User form: password visibility, strength requirements, and dynamic UAC pre-selection
 */
document.addEventListener('DOMContentLoaded', function () {
    // ── Tooltips ────────────────────────────────────────────────────
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.forEach(function (el) {
        new bootstrap.Tooltip(el);
    });

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

    roleSelect.addEventListener('change', function () {
        var selectedRole = this.value;
        var defaults = roleDefaults[selectedRole];
        if (!defaults) return;

        for (var moduleName in defaults) {
            var scopeValue = defaults[moduleName];
            var radioName = 'module_scope__' + moduleName;
            // Find the radio button with matching name and value
            var radio = document.querySelector(
                'input[type="radio"][name="' + radioName + '"][value="' + scopeValue + '"]'
            );
            if (radio) {
                radio.checked = true;
            }
        }
    });
});
