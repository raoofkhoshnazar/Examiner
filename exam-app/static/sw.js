/* Service Worker واژه‌بان — ذخیرهٔ آفلاین پوستهٔ برنامه
   فقط فایل‌های ثابت و صفحهٔ آفلاین کش می‌شوند؛ پاسخ‌های API و صفحه‌های آزمون
   هیچ‌وقت کش نمی‌شوند تا دادهٔ کهنه یا کلید پاسخ جابه‌جا نشود. */
const VERSION = 'vb-v9';
const STATIC_CACHE = VERSION + '-static';
const SHELL = ['/static/style.css', '/static/exam.js', '/static/offline.html',
  '/static/favicon.svg', '/static/icons/icon-192.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k.startsWith('vb-') && k !== STATIC_CACHE).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

function networkFirstOffline(request) {
  return fetch(request).catch(() =>
    caches.match('/static/offline.html').then((hit) => hit || new Response('', { status: 503 }))
  );
}

function cacheFirst(request) {
  return caches.match(request).then((hit) => hit || fetch(request).then((res) => {
    if (res && res.ok) {
      const copy = res.clone();
      caches.open(STATIC_CACHE).then((cache) => cache.put(request, copy)).catch(() => {});
    }
    return res;
  }));
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;               // ارسال پاسخ‌ها و ارسال آزمون هرگز دست‌کاری نمی‌شود
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;    // منابع بیرونی به SW کاری ندارند
  if (url.pathname.startsWith('/api/')) return;       // دادهٔ زنده از کش نمی‌آید

  if (request.mode === 'navigate') {
    event.respondWith(networkFirstOffline(request));
    return;
  }
  if (url.pathname.startsWith('/static/') || url.pathname === '/sw.js') {
    event.respondWith(cacheFirst(request));
  }
});
