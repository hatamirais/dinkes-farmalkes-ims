document.addEventListener('DOMContentLoaded', () => {
    const goBackButton = document.getElementById('goBackButton');
    const fallbackLink = document.getElementById('fallbackLink');
    const fallbackLabel = document.getElementById('fallbackLabel');
    const fallbackIcon = document.getElementById('fallbackIcon');

    if (!goBackButton || !fallbackLink) {
        return;
    }

    const defaultFallback = fallbackLink.getAttribute('href') || '/';
    const previousLabel = fallbackLink.dataset.previousLabel || 'Buka Halaman Terakhir';
    let fallbackUrl = defaultFallback;

    if (document.referrer) {
        try {
            const previousUrl = new URL(document.referrer);
            if (previousUrl.origin === window.location.origin) {
                fallbackUrl = previousUrl.href;
                fallbackLink.setAttribute('href', fallbackUrl);
                if (fallbackLabel) {
                    fallbackLabel.textContent = previousLabel;
                }
                if (fallbackIcon) {
                    fallbackIcon.className = 'bi bi-clock-history me-2';
                }
            }
        } catch (error) {
            fallbackUrl = defaultFallback;
        }
    }

    goBackButton.addEventListener('click', () => {
        if (window.history.length > 1) {
            const fallbackTimer = window.setTimeout(() => {
                window.location.assign(fallbackUrl);
            }, 250);

            window.addEventListener(
                'pageshow',
                () => {
                    window.clearTimeout(fallbackTimer);
                },
                { once: true }
            );

            window.history.back();
            return;
        }

        window.location.assign(fallbackUrl);
    });
});