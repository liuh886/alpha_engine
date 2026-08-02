import { describe, expect, it, vi } from 'vitest';

import { activateServiceWorkerUpdate } from './register-service-worker';

type Listener = () => void;

function mockWorker(initialState: ServiceWorkerState = 'installed') {
  const listeners = new Map<string, Listener>();
  const worker = {
    state: initialState,
    postMessage: vi.fn(),
    addEventListener: vi.fn((type: string, listener: Listener) => {
      listeners.set(type, listener);
    }),
  };
  return {
    worker,
    setState(state: ServiceWorkerState) {
      worker.state = state;
      listeners.get('statechange')?.();
    },
  };
}

describe('activateServiceWorkerUpdate', () => {
  it('forces a waiting worker to activate and reloads once on controller change', async () => {
    const waiting = mockWorker();
    const registrationListeners = new Map<string, Listener>();
    const registration = {
      waiting: waiting.worker,
      installing: null,
      addEventListener: vi.fn((type: string, listener: Listener) => {
        registrationListeners.set(type, listener);
      }),
      update: vi.fn(async () => undefined),
    };
    const containerListeners = new Map<string, Listener>();
    const container = {
      controller: {},
      register: vi.fn(async () => registration),
      addEventListener: vi.fn((type: string, listener: Listener) => {
        containerListeners.set(type, listener);
      }),
    };
    const reload = vi.fn();
    const url = new URL('https://example.test/alpha_engine/sw.js?release_check=1');

    await activateServiceWorkerUpdate(
      container as unknown as ServiceWorkerContainer,
      url,
      reload,
    );

    expect(container.register).toHaveBeenCalledWith(url, {
      scope: './',
      updateViaCache: 'none',
    });
    expect(registration.update).toHaveBeenCalledOnce();
    expect(waiting.worker.postMessage).toHaveBeenCalledWith({ type: 'SKIP_WAITING' });

    containerListeners.get('controllerchange')?.();
    containerListeners.get('controllerchange')?.();
    expect(reload).toHaveBeenCalledOnce();
  });

  it('activates an updated worker as soon as installation completes', async () => {
    const installing = mockWorker('installing');
    const registrationListeners = new Map<string, Listener>();
    const registration = {
      waiting: null,
      installing: installing.worker,
      addEventListener: vi.fn((type: string, listener: Listener) => {
        registrationListeners.set(type, listener);
      }),
      update: vi.fn(async () => {
        registrationListeners.get('updatefound')?.();
        installing.setState('installed');
      }),
    };
    const container = {
      controller: {},
      register: vi.fn(async () => registration),
      addEventListener: vi.fn(),
    };

    await activateServiceWorkerUpdate(
      container as unknown as ServiceWorkerContainer,
      new URL('https://example.test/alpha_engine/sw.js?release_check=2'),
      vi.fn(),
    );

    expect(installing.worker.postMessage).toHaveBeenCalledWith({ type: 'SKIP_WAITING' });
  });
});
