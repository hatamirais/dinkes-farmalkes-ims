document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.querySelector("[data-password-toggle]");
    if (!toggle) {
        return;
    }

    var input = document.getElementById(toggle.dataset.passwordToggle);
    var icon = toggle.querySelector("i");
    var label = toggle.querySelector(".visually-hidden");
    if (!input) {
        return;
    }

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
});
