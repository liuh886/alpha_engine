/**
 * Canvas colors cannot resolve CSS custom properties, so the semantic foundation
 * tokens are read once per theme change and converted to concrete color strings.
 * Fallbacks mirror the light/dark token values in `index.css`; they exist only
 * for environments (canvas, jsdom) where computed style tokens are unavailable.
 */
/**
 * Fixed categorical order for model-attributed series (markers and future
 * overlays). The order is validated with the data-viz palette method against
 * the project's own `--chart-*` tokens: adjacent CVD separation >= 8 and
 * normal-vision separation >= 15 in both modes. `chart-2` is deliberately not
 * in the first five slots because its light token sits below the chroma floor;
 * `chart-1` is last so a model hue rarely collides with the instrument line.
 * Assign by model identity, never by list position or rank.
 */
export const MODEL_SERIES_TOKENS = ['chart-4', 'chart-6', 'chart-3', 'chart-5', 'chart-1'] as const;

/**
 * Fixed categorical order for governed chart indicators, deliberately distinct
 * from `MODEL_SERIES_TOKENS` and from the `positive`/`negative` polarity cues.
 * Validated with the data-viz palette method against the project's own
 * light card `#ffffff` and dark card `#141820` surfaces; adjacent CVD Delta E
 * 7.8-15.2 and normal-vision Delta E >= 15 in both modes. Dark is a separately
 * selected set, not an automatic flip. Assignment follows the indicator family,
 * never list position or rank.
 */
export const INDICATOR_SERIES_TOKENS = [
  'indicator-1',
  'indicator-2',
  'indicator-3',
  'indicator-4',
] as const;

const MODEL_SERIES_FALLBACKS: Readonly<Record<'light' | 'dark', readonly string[]>> = {
  light: [
    'hsl(22, 88%, 46%)',
    'hsl(199, 75%, 38%)',
    'hsl(38, 95%, 37%)',
    'hsl(329, 55%, 48%)',
    'hsl(210, 90%, 40%)',
  ],
  dark: [
    'hsl(24, 92%, 65%)',
    'hsl(199, 82%, 64%)',
    'hsl(42, 92%, 60%)',
    'hsl(330, 66%, 70%)',
    'hsl(207, 88%, 66%)',
  ],
};

const INDICATOR_SERIES_FALLBACKS: Readonly<Record<'light' | 'dark', readonly string[]>> = {
  light: [
    'hsl(248, 62%, 58%)',
    'hsl(159, 73%, 40%)',
    'hsl(23, 67%, 31%)',
    'hsl(334, 80%, 40%)',
  ],
  dark: [
    'hsl(247, 69%, 72%)',
    'hsl(159, 73%, 36%)',
    'hsl(24, 59%, 45%)',
    'hsl(335, 62%, 61%)',
  ],
};

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
  /**
   * Concrete model-series colors in `MODEL_SERIES_TOKENS` order. Canvas cannot
   * resolve CSS custom properties, so these are read and converted per theme.
   */
  modelSeries: readonly string[];
  /**
   * Concrete indicator colors in `INDICATOR_SERIES_TOKENS` order. Kept distinct
   * from model identity and from positive/negative polarity.
   */
  indicatorSeries: readonly string[];
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
  const mode = isDark ? 'dark' : 'light';
  const modelFallbacks = MODEL_SERIES_FALLBACKS[mode];
  const indicatorFallbacks = INDICATOR_SERIES_FALLBACKS[mode];
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
    modelSeries: MODEL_SERIES_TOKENS.map((name, index) => hsl(token(name), modelFallbacks[index] ?? modelFallbacks[0])),
    indicatorSeries: INDICATOR_SERIES_TOKENS.map(
      (name, index) => hsl(token(name), indicatorFallbacks[index] ?? indicatorFallbacks[0]),
    ),
  };
}
