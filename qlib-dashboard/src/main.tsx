import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.tsx';
import { ErrorBoundary } from './components/ErrorBoundary';
import { initializeUiLanguage } from './lib/ui-language';
import './index.css';

initializeUiLanguage();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);

// Remove only this application's old worker; other projects on this origin are independent.
if (typeof navigator.serviceWorker?.getRegistrations === 'function') {
  const scope = new URL('./', document.baseURI).href;
  void navigator.serviceWorker.getRegistrations().then(async registrations => {
    await Promise.all(registrations.filter(registration => registration.scope === scope).map(registration => registration.unregister()));
    if ('caches' in window) {
      const keys = await caches.keys();
      await Promise.all(keys.filter(key => key.startsWith('alpha-engine-shell-')).map(key => caches.delete(key)));
    }
  }).catch(() => { /* A retired worker must not block the current reader. */ });
}
