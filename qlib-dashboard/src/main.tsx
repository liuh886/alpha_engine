import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.tsx';
import { ErrorBoundary } from './components/ErrorBoundary';
import { initializeAnalytics } from './lib/analytics';
import { initializeUiLanguage } from './lib/ui-language';
import { registerServiceWorker } from './lib/register-service-worker';
import './index.css';

initializeUiLanguage();
initializeAnalytics();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);

registerServiceWorker();
