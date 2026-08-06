export const GA_MEASUREMENT_ID = 'G-18RES38PZ5';

type Gtag = (...args: unknown[]) => void;

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: Gtag;
    __alphaEngineGa4Initialized?: boolean;
  }
}

export function buildPagePath(
  location: Pick<Location, 'pathname' | 'search' | 'hash'>,
): string {
  return `${location.pathname}${location.search}${location.hash}`;
}

function ensureGoogleTag(): Gtag {
  window.dataLayer = window.dataLayer ?? [];
  window.gtag = window.gtag ?? function gtag(...args: unknown[]) {
    window.dataLayer?.push(args);
  };

  const selector = `script[src*="googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}"]`;
  if (!document.querySelector(selector)) {
    const script = document.createElement('script');
    script.async = true;
    script.src = `https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`;
    document.head.appendChild(script);
  }

  return window.gtag;
}

export function trackPageView(): void {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  const gtag = ensureGoogleTag();
  gtag('event', 'page_view', {
    page_title: document.title,
    page_location: window.location.href,
    page_path: buildPagePath(window.location),
  });
}

export function initializeAnalytics(): void {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  if (window.__alphaEngineGa4Initialized) return;
  window.__alphaEngineGa4Initialized = true;

  const gtag = ensureGoogleTag();
  gtag('js', new Date());
  gtag('config', GA_MEASUREMENT_ID, { send_page_view: false });

  const schedulePageView = () => {
    window.requestAnimationFrame(() => trackPageView());
  };

  schedulePageView();
  window.addEventListener('hashchange', schedulePageView);
}
