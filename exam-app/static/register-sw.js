/* ثبت Service Worker برای ذخیرهٔ آفلاین پوستهٔ برنامه */
(function () {
  if (!('serviceWorker' in navigator)) return;
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('/sw.js').catch(function () { /* آفلاین هم بدون SW کار می‌کند */ });
  });
})();
