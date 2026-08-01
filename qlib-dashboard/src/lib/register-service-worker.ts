import { runtimeCapabilities } from './runtime-capabilities';

export function registerServiceWorker(): void {
  if (!import.meta.env.PROD || !runtimeCapabilities.offlineShell) return;
  if (!('serviceWorker' in navigator)) return;

  window.addEventListener('load', () => {
    const serviceWorkerUrl = new URL('sw.js', document.baseURI);
    navigator.serviceWorker.register(serviceWorkerUrl, { scope: './' }).catch((error) => {
      console.warn('[pwa] Service worker registration failed.', error);
    });
  });
}
