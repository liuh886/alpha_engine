const CLOUDFLARE_WEB_ANALYTICS_SRC = 'https://static.cloudflareinsights.com/beacon.min.js';

declare global {
  interface Window {
    __alphaEngineCloudflareAnalyticsInitialized?: boolean;
  }
}

export function initializeAnalytics(): void {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  if (window.__alphaEngineCloudflareAnalyticsInitialized) return;

  const token = String(import.meta.env.VITE_CLOUDFLARE_WEB_ANALYTICS_TOKEN ?? '').trim();
  if (!token) return;

  window.__alphaEngineCloudflareAnalyticsInitialized = true;
  const script = document.createElement('script');
  script.defer = true;
  script.src = CLOUDFLARE_WEB_ANALYTICS_SRC;
  script.setAttribute('data-cf-beacon', JSON.stringify({ token }));
  document.head.appendChild(script);
}
