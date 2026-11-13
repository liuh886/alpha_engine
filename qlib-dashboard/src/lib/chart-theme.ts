/**
 * Canvas colors cannot resolve CSS custom properties, so the semantic foundation
 * tokens are read once per theme change and converted to concrete color strings.
 * Fallbacks mirror the light/dark token values in `index.css`; they exist only
 * for environments (canvas, jsdom) where computed style tokens are unavailable.
 */
export interface ChartTheme {
  text: string;
  grid: string;
  border: string;
  crosshair: string;
  /** Instrument/primary series line. */
  primary: string;
  /** Market baseline comparison line. */
  baseline: string;
  candleUp: string;
  candleDown: string;
  volumeUp: string;
  volumeDown: string;
  /** Buy/increase marker. */
  positive: string;
  /** Sell/decrease marker. */
  negative: string;
}

function token(name: string): string {
  try {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
    return raw;
  } catch {
    return '';
  }
}

/** Convert a space-separated HSL token (`220 16% 90%`) into a canvas color. */
function hsl(raw: string, fallback: string): string {
  if (!raw) return fallback;
  const normalized = raw.includes(',') ? raw : raw.split(/\s+/).join(', ');
  return `hsl(${normalized})`;
}

function hsla(raw: string, alpha: number, fallback: string): string {
  if (!raw) return fallback;
  const parts = raw.replace(/,/g, ' ').split(/\s+/).filter(Boolean);
  if (parts.length < 3) return fallback;
  return `hsla(${parts[0]}, ${parts[1]}, ${parts[2]}, ${alpha})`;
}

export function chartTheme(isDark: boolean): ChartTheme {
  return {
    text: hsl(token('chart-axis'), isDark ? '#94a3b8' : '#64748b'),
    grid: hsl(token('chart-grid'), isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(15, 23, 42, 0.07)'),
    border: hsl(token('border'), isDark ? 'rgba(255, 255, 255, 0.14)' : 'rgba(15, 23, 42, 0.14)'),
    crosshair: hsl(token('chart-axis'), isDark ? '#94a3b8' : '#64748b'),
    primary: hsl(token('chart-1'), isDark ? 'hsl(207, 88%, 66%)' : 'hsl(210, 90%, 40%)'),
    baseline: hsl(token('chart-2'), isDark ? 'hsl(172, 55%, 50%)' : 'hsl(173, 85%, 27%)'),
    candleUp: hsl(token('positive'), isDark ? 'hsl(152, 52%, 58%)' : 'hsl(152, 62%, 28%)'),
    candleDown: hsl(token('negative'), isDark ? 'hsl(0, 78%, 68%)' : 'hsl(0, 68%, 43%)'),
    volumeUp: hsla(token('positive'), 0.4, isDark ? 'rgba(84, 196, 148, 0.4)' : 'rgba(5, 150, 105, 0.4)'),
    volumeDown: hsla(token('negative'), 0.4, isDark ? 'rgba(242, 128, 128, 0.4)' : 'rgba(225, 29, 72, 0.4)'),
    positive: hsl(token('positive'), isDark ? 'hsl(152, 52%, 58%)' : 'hsl(152, 62%, 28%)'),
    negative: hsl(token('negative'), isDark ? 'hsl(0, 78%, 68%)' : 'hsl(0, 68%, 43%)'),
  };
}
