(function () {
  const installBanner = document.querySelector("[data-pwa-install]");
  const installText = document.querySelector("[data-pwa-install-text]");
  const installButton = document.querySelector("[data-pwa-install-button]");
  const dismissButton = document.querySelector("[data-pwa-install-dismiss]");
  const dismissKey = "imsMobileInstallPromptDismissed";
  let deferredInstallPrompt = null;

  function storageGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (error) {
      return null;
    }
  }

  function storageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (error) {
      // Private browsing or locked-down browsers may block storage.
    }
  }

  function isStandalone() {
    return (
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true
    );
  }

  function isPhoneSized() {
    return window.matchMedia("(max-width: 48rem)").matches;
  }

  function isIosSafariLike() {
    const ua = window.navigator.userAgent || "";
    const iOSDevice = /iphone|ipad|ipod/i.test(ua);
    const iPadOS = /macintosh/i.test(ua) && window.navigator.maxTouchPoints > 1;
    return iOSDevice || iPadOS;
  }

  function hideInstallBanner() {
    if (installBanner) {
      installBanner.hidden = true;
    }
  }

  function showInstallBanner(mode) {
    if (!installBanner || !isPhoneSized() || isStandalone() || storageGet(dismissKey) === "true") {
      return;
    }

    if (mode === "native" && installButton) {
      installButton.hidden = false;
      if (installText) {
        installText.textContent = "Tambahkan ke layar utama agar akses cek stok lebih cepat.";
      }
    } else {
      if (installButton) {
        installButton.hidden = true;
      }
      if (installText) {
        installText.textContent = isIosSafariLike()
          ? "Buka menu Bagikan, lalu pilih Tambahkan ke Layar Utama."
          : "Gunakan menu browser, lalu pilih instal atau tambahkan ke layar utama.";
      }
    }

    installBanner.hidden = false;
  }

  if (dismissButton) {
    dismissButton.addEventListener("click", function () {
      storageSet(dismissKey, "true");
      hideInstallBanner();
    });
  }

  if (installButton) {
    installButton.addEventListener("click", function () {
      if (!deferredInstallPrompt) {
        showInstallBanner("manual");
        return;
      }

      deferredInstallPrompt.prompt();
      deferredInstallPrompt.userChoice.finally(function () {
        deferredInstallPrompt = null;
        storageSet(dismissKey, "true");
        hideInstallBanner();
      });
    });
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferredInstallPrompt = event;
    showInstallBanner("native");
  });

  window.addEventListener("appinstalled", function () {
    storageSet(dismissKey, "true");
    hideInstallBanner();
  });

  window.addEventListener("load", function () {
    window.setTimeout(function () {
      if (!deferredInstallPrompt) {
        showInstallBanner("manual");
      }
    }, 1200);
  });

  if (!("serviceWorker" in navigator)) {
    return;
  }

  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/mobile/service-worker.js/").catch(function () {
      // Mobile pages remain usable without service worker support.
    });
  });
})();
