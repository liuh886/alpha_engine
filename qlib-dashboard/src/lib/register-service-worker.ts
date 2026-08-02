import { runtimeCapabilities } from './runtime-capabilities';

export function registerServiceWorker(): void {
  if (!import.meta.env.PROD || !runtimeCapabilities.offlineShell) return;
  if (!('serviceWorker' in navigator)) return;

  window.addEventListener('load', () => {
    const serviceWorkerUrl = new URL('sw.js', document.baseURI);
    const hadController = Boolean(navigator.serviceWorker.controller);
    let refreshing = false;

    if (hadController) {
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (refreshing) return;
        refreshing = true;
        window.location.reload();
      });
    }

    navigator.serviceWorker
      .register(serviceWorkerUrl, {
        scope: './',
        updateViaCache: 'none',
      })
      .then((registration) => registration.update())
      .catch((error) => {
        console.warn('[pwa] Service worker registration failed.', error);
      });
  });
}
