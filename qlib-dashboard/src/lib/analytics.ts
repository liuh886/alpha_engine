export const GA_MEASUREMENT_ID = 'G-18RES38PZ5';
export const CLOUDFLARE_WEB_ANALYTICS_SRC = 'https://static.cloudflareinsights.com/beacon.min.js';
const GOOGLE_TAG_SRC = `https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`;

type Gtag = (...args: unknown[]) => void;

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: Gtag;
    __alphaEngineAnalyticsInitialized?: boolean;
  }
}

export function buildPagePath(
  location: Pick<Location, 'pathname' | 'search' | 'hash'>,
): string {
  return `${location.pathname}${location.search}${location.hash}`;
}

export function viewFromHash(hash: string): string {
  const route = hash.replace(/^#\/?/, '').split('?')[0].replace(/^\/+|\/+$/g, '');
  return route.split('/')[0] || 'landing';
}

function ensureGoogleTag(): Gtag | null {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;

  window.dataLayer = window.dataLayer ?? [];
  window.gtag = window.gtag ?? function gtag(...args: unknown[]) {
    window.dataLayer?.push(args);
  };

  if (!document.querySelector(`script[src="${GOOGLE_TAG_SRC}"]`)) {
    const script = document.createElement('script');
    script.async = true;
    script.src = GOOGLE_TAG_SRC;
    document.head.appendChild(script);
  }

  return window.gtag;
}

function initializeGoogleAnalytics(): void {
  const gtag = ensureGoogleTag();
  if (!gtag) return;
  gtag('js', new Date());
  gtag('config', GA_MEASUREMENT_ID, { send_page_view: false });
}

function initializeCloudflareAnalytics(): void {
  const token = String(import.meta.env.VITE_CLOUDFLARE_WEB_ANALYTICS_TOKEN ?? '').trim();
  if (!token || typeof document === 'undefined') return;
  if (document.querySelector(`script[src="${CLOUDFLARE_WEB_ANALYTICS_SRC}"]`)) return;

  const script = document.createElement('script');
  script.defer = true;
  script.src = CLOUDFLARE_WEB_ANALYTICS_SRC;
  script.setAttribute('data-cf-beacon', JSON.stringify({ token }));
  document.head.appendChild(script);
}

export function trackCurrentRoute(): void {
  const gtag = window.gtag;
  if (!gtag) return;

  const pagePath = buildPagePath(window.location);
  const view = viewFromHash(window.location.hash);
  gtag('event', 'page_view', {
    page_title: document.title,
    page_location: window.location.href,
    page_path: pagePath,
  });
  gtag('event', 'strategy_console_view', { view });
}

export function initializeAnalytics(): void {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  if (window.__alphaEngineAnalyticsInitialized) return;
  window.__alphaEngineAnalyticsInitialized = true;

  initializeGoogleAnalytics();
  initializeCloudflareAnalytics();
  trackCurrentRoute();
  window.addEventListener('hashchange', () => window.requestAnimationFrame(trackCurrentRoute));
}
