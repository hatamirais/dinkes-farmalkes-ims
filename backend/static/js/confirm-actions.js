/**
 * Declarative confirm dialog for forms and buttons.
 * Replaces inline onclick="return confirm(...)" and onsubmit="return confirm(...)".
 *
 * Usage:
 *   <form data-confirm-submit="Are you sure?"> ... </form>
 *   <button data-confirm-click="Delete this?" onclick="window.print()"> ... </button>
 */
document.addEventListener('DOMContentLoaded', function () {
    // Form submit confirmations
    document.querySelectorAll('[data-confirm-submit]').forEach(function (form) {
        form.addEventListener('submit', function (e) {
            var message = form.getAttribute('data-confirm-submit');
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });

    // Button/click confirmations (for buttons that are type="submit" in a form)
    document.querySelectorAll('[data-confirm-click]').forEach(function (el) {
        el.addEventListener('click', function (e) {
            var message = el.getAttribute('data-confirm-click');
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });

    // Print buttons
    document.querySelectorAll('[data-action="print"]').forEach(function (el) {
        el.addEventListener('click', function () {
            window.print();
        });
    });

    // Close window buttons
    document.querySelectorAll('[data-action="close"]').forEach(function (el) {
        el.addEventListener('click', function () {
            window.close();
        });
    });

    // Auto-submit on change
    document.querySelectorAll('[data-action="submit-on-change"]').forEach(function (el) {
        el.addEventListener('change', function () {
            var form = el.closest('form');
            if (form) form.submit();
        });
    });
});
