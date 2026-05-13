const CACHE_NAME = 'airport-weather-v3';

self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.map(key => caches.delete(key))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  
  if (url.hostname === 'aviationweather.gov' || url.hostname.includes('allorigins') || url.hostname.includes('codetabs')) {
    return; 
  }

  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});