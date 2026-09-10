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

  function initMobileStockSearch() {
    const form = document.querySelector("[data-mobile-stock-search]");
    if (!form) {
      return;
    }

    const results = document.querySelector(form.dataset.resultsTarget || "");
    const nextContainer = document.querySelector(form.dataset.nextTarget || "");
    const countLabel = document.querySelector("[data-mobile-result-count]");
    const entryCountLabel = document.querySelector("[data-mobile-entry-count]");
    const quickCountLabels = {
      expired: document.querySelector("[data-mobile-quick-count='expired']"),
      expiring: document.querySelector("[data-mobile-quick-count='expiring']"),
      safe: document.querySelector("[data-mobile-quick-count='safe']"),
    };
    const searchInput = form.querySelector("input[name='q']");
    let loading = false;
    let debounceTimer = null;
    let activeController = null;
    let loadSequence = 0;

    function buildUrl(page) {
      const url = new URL(form.action || window.location.href, window.location.origin);
      const formData = new FormData(form);

      url.search = "";
      formData.forEach(function (value, key) {
        if (value) {
          url.searchParams.append(key, value);
        }
      });
      url.searchParams.set("page", String(page));
      url.searchParams.set("partial", "1");
      return url;
    }

    function updateNext(response, sourceUrl) {
      if (!nextContainer) {
        return;
      }

      const hasNext = response.headers.get("X-Has-Next") === "1";
      const nextPage = response.headers.get("X-Next-Page");
      if (!hasNext || !nextPage) {
        nextContainer.removeAttribute("href");
        nextContainer.textContent = "Selesai";
        nextContainer.dataset.loading = "false";
        return;
      }

      const nextUrl = new URL(sourceUrl.toString());
      nextUrl.searchParams.set("page", nextPage);
      nextUrl.searchParams.delete("partial");
      nextContainer.href = `${nextUrl.pathname}${nextUrl.search}`;
      nextContainer.textContent = "Muat lagi";
      nextContainer.dataset.loading = "false";
    }

    function updateStats(response) {
      [
        ["expired", "X-Quick-Expired"],
        ["expiring", "X-Quick-Expiring"],
        ["safe", "X-Quick-Safe"],
      ].forEach(function ([key, headerName]) {
        const value = response.headers.get(headerName);
        if (quickCountLabels[key] && value !== null) {
          quickCountLabels[key].textContent = value;
        }
      });
    }

    function fullPageUrl(sourceUrl) {
      const cleanUrl = new URL(sourceUrl.toString());
      cleanUrl.searchParams.delete("partial");
      cleanUrl.searchParams.delete("page");
      return `${cleanUrl.pathname}${cleanUrl.search}`;
    }

    async function loadPage(page, mode) {
      if (!results) {
        return;
      }

      if (loading && mode !== "replace") {
        return;
      }

      if (mode === "replace" && activeController) {
        activeController.abort();
      }

      loading = true;
      if (nextContainer) {
        nextContainer.dataset.loading = "true";
        nextContainer.textContent = "Memuat...";
      }

      activeController = new AbortController();
      const requestId = loadSequence + 1;
      loadSequence = requestId;
      const url = buildUrl(page);

      try {
        const response = await fetch(url, {
          headers: { "X-Requested-With": "XMLHttpRequest" },
          signal: activeController.signal,
        });
        if (requestId !== loadSequence) {
          return;
        }
        if (!response.ok || response.redirected) {
          window.location.href = fullPageUrl(url);
          return;
        }

        const html = await response.text();
        if (mode === "append") {
          results.insertAdjacentHTML("beforeend", html);
        } else {
          results.innerHTML = html;
          window.history.replaceState({}, "", fullPageUrl(url));
        }

        if (countLabel) {
          const count = response.headers.get("X-Result-Count");
          if (count) {
            countLabel.textContent = count;
          }
        }
        if (entryCountLabel) {
          const entryCount = response.headers.get("X-Entry-Count");
          if (entryCount) {
            entryCountLabel.textContent = entryCount;
          }
        }
        updateStats(response);
        updateNext(response, url);
      } catch (error) {
        if (error.name !== "AbortError" && nextContainer) {
          nextContainer.textContent = "Gagal memuat";
        }
      } finally {
        if (requestId === loadSequence) {
          loading = false;
          activeController = null;
        }
      }
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      loadPage(1, "replace");
    });

    if (searchInput) {
      searchInput.addEventListener("input", function () {
        window.clearTimeout(debounceTimer);
        debounceTimer = window.setTimeout(function () {
          loadPage(1, "replace");
        }, 350);
      });
    }

    if (nextContainer) {
      nextContainer.addEventListener("click", function (event) {
        if (!nextContainer.href) {
          return;
        }
        event.preventDefault();
        const nextUrl = new URL(nextContainer.href);
        loadPage(nextUrl.searchParams.get("page") || "1", "append");
      });

      if ("IntersectionObserver" in window) {
        const observer = new IntersectionObserver(function (entries) {
          if (entries.some(function (entry) { return entry.isIntersecting; }) && nextContainer.href) {
            const nextUrl = new URL(nextContainer.href);
            loadPage(nextUrl.searchParams.get("page") || "1", "append");
          }
        }, { rootMargin: "320px 0px" });
        observer.observe(nextContainer);
      }
    }
  }

  document.addEventListener("DOMContentLoaded", initMobileStockSearch);

  if (!("serviceWorker" in navigator)) {
    return;
  }

  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/mobile/service-worker.js/").catch(function () {
      // Mobile pages remain usable without service worker support.
    });
  });
})();
