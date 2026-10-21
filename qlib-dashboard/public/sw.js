// Retire the old offline shell for existing installations. New clients do not register a worker.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key.startsWith('alpha-engine-shell-')).map(key => caches.delete(key))))
      .then(() => self.registration.unregister())
  );
});
