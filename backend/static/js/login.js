/**
 * Login page: password visibility toggle
 */
document.addEventListener('DOMContentLoaded', function () {
    var toggleBtn = document.getElementById('togglePassword');
    if (!toggleBtn) return;

    toggleBtn.addEventListener('click', function () {
        var input = document.getElementById('id_password');
        var icon = this.querySelector('i');
        if (input.type === 'password') {
            input.type = 'text';
            icon.classList.replace('bi-eye-slash', 'bi-eye');
            this.setAttribute('aria-label', 'Sembunyikan kata sandi');
            this.setAttribute('aria-pressed', 'true');
        } else {
            input.type = 'password';
            icon.classList.replace('bi-eye', 'bi-eye-slash');
            this.setAttribute('aria-label', 'Tampilkan kata sandi');
            this.setAttribute('aria-pressed', 'false');
        }
    });
});
