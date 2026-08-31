import { runtimeCapabilities } from './runtime-capabilities';

const SERVICE_WORKER_RELEASE = 'v5';
const SKIP_WAITING_MESSAGE = { type: 'SKIP_WAITING' } as const;

function requestActivation(worker: ServiceWorker | null): void {
  worker?.postMessage(SKIP_WAITING_MESSAGE);
}

export async function activateServiceWorkerUpdate(
  container: ServiceWorkerContainer,
  serviceWorkerUrl: URL,
  reload: () => void,
): Promise<void> {
  const hadController = Boolean(container.controller);
  let refreshing = false;

  if (hadController) {
    container.addEventListener('controllerchange', () => {
      if (refreshing) return;
      refreshing = true;
      reload();
    });
  }

  const registration = await container.register(serviceWorkerUrl, {
    scope: './',
    updateViaCache: 'none',
  });

  requestActivation(registration.waiting);
  registration.addEventListener('updatefound', () => {
    const installingWorker = registration.installing;
    if (!installingWorker) return;

    const activateWhenInstalled = () => {
      if (installingWorker.state === 'installed' && container.controller) {
        requestActivation(installingWorker);
      }
    };
    installingWorker.addEventListener('statechange', activateWhenInstalled);
    activateWhenInstalled();
  });

  await registration.update();
  requestActivation(registration.waiting);
}

export function registerServiceWorker(): void {
  if (!import.meta.env.PROD || !runtimeCapabilities.offlineShell) return;
  if (!('serviceWorker' in navigator)) return;

  window.addEventListener('load', () => {
    const serviceWorkerUrl = new URL('sw.js', document.baseURI);
    serviceWorkerUrl.searchParams.set('release_check', SERVICE_WORKER_RELEASE);

    void activateServiceWorkerUpdate(
      navigator.serviceWorker,
      serviceWorkerUrl,
      () => window.location.reload(),
    ).catch((error: unknown) => {
      console.warn('[pwa] Service worker registration failed.', error);
    });
  });
}
