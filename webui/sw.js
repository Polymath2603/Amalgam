const CACHE_NAME = 'amalgam-v1';
const SHELL_URLS = [
  '/',
  '/index.html',
  '/css/style.css',
  '/js/app.js',
  '/js/avatar.js',
  '/js/adaptive-lipsync.js',
  '/js/vrm-animation.js',
  '/js/speech-bubble.js',
  '/js/custom-select.js',
  '/js/utils.js',
  '/js/three.min.js',
  '/js/three-vrm.js',
  '/manifest.json',
];

// Install: cache the app shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(SHELL_URLS);
    })
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      );
    })
  );
  self.clients.claim();
});

// Fetch: cache-first for shell, network-first for VRM/audio/assets
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // VRM and audio files are large — network-first, cache fallback
  if (url.pathname.match(/\.(vrm|vrma|wav|mp3|ogg|png|jpg)$/i)) {
    event.respondWith(
      caches.open('amalgam-assets').then((cache) => {
        return fetch(event.request)
          .then((res) => { cache.put(event.request, res.clone()); return res; })
          .catch(() => caches.match(event.request));
      })
    );
    return;
  }

  // API calls — network only
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(event.request));
    return;
  }

  // Everything else — cache-first
  event.respondWith(
    caches.match(event.request).then((cached) => {
      return cached || fetch(event.request).then((res) => {
        if (res.ok && url.origin === location.origin) {
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, res.clone()));
        }
        return res;
      });
    })
  );
});
