const CACHE_NAME = 'amalgam-v2';
const SHELL_URLS = [
  '/',
  '/index.html',
  '/css/style.css',
  '/js/app.js',
  '/js/avatar.js',
  '/js/adaptive-lipsync.js',
  '/js/vrm-animation.js',
  '/js/custom-select.js',
  '/js/idle-manager.js',
  '/js/frequency-analyzer.js',
  '/js/viseme-scheduler.js',
  '/js/visemes.js',
  '/js/audio-utils.js',
  '/js/modules/api-client.js',
  '/js/modules/config.js',
  '/js/modules/health.js',
  '/js/modules/history.js',
  '/js/modules/markdown.js',
  '/js/modules/mcp.js',
  '/js/modules/mcp-command.js',
  '/js/modules/settings-schema.js',
  '/js/modules/settings.js',
  '/js/modules/setup-wizard.js',
  '/js/modules/state.js',
  '/js/modules/tts.js',
  '/js/modules/utils.js',
  '/js/modules/voice.js',
  '/js/modules/ws.js',
  '/js/i18n.js',
  '/js/metrics.js',
  '/js/swarm.js',
  '/vendor/d3.min.js',
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
      fetch(event.request)
        .then((res) => {
          if (!res || !res.ok) return caches.match(event.request);
          return caches.open('amalgam-assets').then((cache) => {
            cache.put(event.request, res.clone());
            return res;
          });
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // API calls — network only
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(event.request).catch(() => new Response(null, { status: 503 })));
    return;
  }

  // Everything else — cache-first
  event.respondWith(
    caches.match(event.request).then((cached) => {
      return cached || fetch(event.request).then((res) => {
        if (res.ok && url.origin === location.origin) {
          const cloned = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, cloned));
        }
        return res;
      });
    })
  );
});
