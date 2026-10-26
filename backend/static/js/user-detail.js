function toSafeSameOriginUrl(urlValue) {
    try {
        var parsed = new URL(urlValue, window.location.origin);
        if ((parsed.protocol === 'http:' || parsed.protocol === 'https:') &&
            parsed.origin === window.location.origin) {
            return parsed.href;
        }
    } catch (e) {}
    return null;
}

document.querySelectorAll('.ims-user-detail .copy-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
        var text = this.getAttribute('data-copy');
        navigator.clipboard.writeText(text).then(function () {
            var icon = btn.querySelector('i');
            icon.className = 'bi bi-check text-success';
            setTimeout(function () { icon.className = 'bi bi-clipboard'; }, 1500);
        }).catch(function () {});
    });
});

document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !e.target.closest('input,textarea,select')) {
        var listUrl = document.querySelector('.ims-user-detail')?.getAttribute('data-users-list-url');
        var safeListUrl = listUrl ? toSafeSameOriginUrl(listUrl) : null;
        if (safeListUrl) window.location.href = safeListUrl;
    }
});
