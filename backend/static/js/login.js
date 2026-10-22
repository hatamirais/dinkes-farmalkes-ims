document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.querySelector("[data-password-toggle]");
    var form = document.querySelector(".auth-form");

    if (toggle) {
        var input = document.getElementById(toggle.dataset.passwordToggle);
        var icon = toggle.querySelector("i");
        var label = toggle.querySelector(".sr-only");

        if (input) {
            toggle.addEventListener("click", function () {
                var isHidden = input.type === "password";
                input.type = isHidden ? "text" : "password";
                toggle.setAttribute("aria-pressed", isHidden ? "true" : "false");
                toggle.setAttribute(
                    "aria-label",
                    isHidden ? "Sembunyikan kata sandi" : "Tampilkan kata sandi"
                );
                if (label) {
                    label.textContent = isHidden
                        ? "Sembunyikan kata sandi"
                        : "Tampilkan kata sandi";
                }
                if (icon) {
                    icon.classList.toggle("bi-eye", !isHidden);
                    icon.classList.toggle("bi-eye-slash", isHidden);
                }
            });
        }
    }

    if (form) {
        form.addEventListener("submit", function () {
            var submitButton = form.querySelector('button[type="submit"]');
            if (!submitButton || submitButton.disabled) {
                return;
            }
            var spinner = submitButton.querySelector(".spinner-border");
            var icon = submitButton.querySelector("i");
            var label = submitButton.querySelector(".auth-submit-label");

            submitButton.disabled = true;
            submitButton.setAttribute("aria-busy", "true");
            if (spinner) {
                spinner.classList.remove("hidden");
            }
            if (icon) {
                icon.classList.add("hidden");
            }
            if (label) {
                label.textContent = "Memproses...";
            }
        });
    }
});
