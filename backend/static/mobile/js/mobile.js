(function () {
  if (!("serviceWorker" in navigator)) {
    return;
  }

  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/mobile/service-worker.js/").catch(function () {
      // Mobile pages remain usable without service worker support.
    });
  });
})();
