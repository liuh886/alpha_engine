import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Committed mirror of the data-viz palette validator for the chart tokens in
 * `index.css`. The validator itself is an external authoring aid; this test
 * pins the measured properties so a future token edit cannot silently regress
 * CVD separation, the normal-vision floor, the mode lightness band, chroma or
 * surface contrast. Numbers match `scripts/validate_palette.js` (OKLab Delta E
 * x100, Machado 2009 severity-1.0 protan/deutan, WCAG contrast).
 */

const CSS = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8');
const LIGHT_SURFACE = '#ffffff';
const DARK_SURFACE = '#141820';
const BAND = { light: [0.43, 0.77], dark: [0.48, 0.67] } as const;
const CHROMA_FLOOR = 0.1;
const CVD_TARGET = 8;
const NORMAL_FLOOR = 15;
const CONTRAST_MIN = 3;

/** Same fixed order the chart assigns identities in. */
const MODEL_ORDER = ['chart-4', 'chart-6', 'chart-3', 'chart-5', 'chart-1'] as const;
const INDICATOR_ORDER = ['indicator-1', 'indicator-2', 'indicator-3', 'indicator-4'] as const;
const ENTITY_ORDER = ['entity-1', 'entity-2', 'entity-3', 'entity-4'] as const;
const STATUS_ORDER = ['positive', 'negative', 'warning'] as const;

interface HslToken {
  h: number;
  s: number;
  l: number;
}

function block(css: string, selector: string): Map<string, HslToken> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`Missing ${selector} block.`);
  const open = css.indexOf('{', start);
  const close = css.indexOf('}', open);
  const body = css.slice(open + 1, close);
  const tokens = new Map<string, HslToken>();
  const pattern = /--([a-z0-9-]+):\s*([\d.]+)\s+([\d.]+)%\s+([\d.]+)%/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(body)) !== null) {
    tokens.set(match[1], { h: Number(match[2]), s: Number(match[3]), l: Number(match[4]) });
  }
  return tokens;
}

function hslToHex({ h, s, l }: HslToken): string {
  const sat = s / 100;
  const light = l / 100;
  const c = (1 - Math.abs(2 * light - 1)) * sat;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = light - c / 2;
  let r = 0;
  let g = 0;
  let b = 0;
  if (h < 60) {
    r = c; g = x;
  } else if (h < 120) {
    r = x; g = c;
  } else if (h < 180) {
    g = c; b = x;
  } else if (h < 240) {
    g = x; b = c;
  } else if (h < 300) {
    r = x; b = c;
  } else {
    r = c; b = x;
  }
  const channel = (value: number) => Math.round((value + m) * 255).toString(16).padStart(2, '0');
  return `#${channel(r)}${channel(g)}${channel(b)}`;
}

const srgbToLinear = (value: number) => (
  value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
);

function linearRgb(hex: string): [number, number, number] {
  return [0, 2, 4].map(index => srgbToLinear(parseInt(hex.slice(index + 1, index + 3), 16) / 255)) as [
    number,
    number,
    number,
  ];
}

function oklab([r, g, b]: [number, number, number]): [number, number, number] {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
  ];
}

const MACHADO = {
  protan: [
    [0.152286, 1.052583, -0.204868],
    [0.114503, 0.786281, 0.099216],
    [-0.003882, -0.048116, 1.051998],
  ],
  deutan: [
    [0.367322, 0.860646, -0.227968],
    [0.280085, 0.672501, 0.047413],
    [-0.011820, 0.042940, 0.968881],
  ],
} as const;

function simulate(rgb: [number, number, number], kind: keyof typeof MACHADO): [number, number, number] {
  const matrix = MACHADO[kind];
  const clamp = (value: number) => Math.max(0, Math.min(1, value));
  return [
    clamp(matrix[0][0] * rgb[0] + matrix[0][1] * rgb[1] + matrix[0][2] * rgb[2]),
    clamp(matrix[1][0] * rgb[0] + matrix[1][1] * rgb[1] + matrix[1][2] * rgb[2]),
    clamp(matrix[2][0] * rgb[0] + matrix[2][1] * rgb[1] + matrix[2][2] * rgb[2]),
  ];
}

function deltaE(a: string, b: string, kind?: keyof typeof MACHADO): number {
  const rgbA = linearRgb(a);
  const rgbB = linearRgb(b);
  const labA = oklab(kind ? simulate(rgbA, kind) : rgbA);
  const labB = oklab(kind ? simulate(rgbB, kind) : rgbB);
  return 100 * Math.hypot(labA[0] - labB[0], labA[1] - labB[1], labA[2] - labB[2]);
}

function cvdDeltaE(a: string, b: string): number {
  return Math.min(deltaE(a, b, 'protan'), deltaE(a, b, 'deutan'));
}

function relativeLuminance(hex: string): number {
  const [r, g, b] = linearRgb(hex);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [high, low] = [relativeLuminance(a), relativeLuminance(b)].sort((left, right) => right - left);
  return (high + 0.05) / (low + 0.05);
}

function oklch(hex: string): { L: number; C: number } {
  const [L, a, b] = oklab(linearRgb(hex));
  return { L, C: Math.hypot(a, b) };
}

const light = block(CSS, ':root');
const dark = block(CSS, '.dark');

function family(tokens: Map<string, HslToken>, names: readonly string[]): string[] {
  return names.map(name => {
    const token = tokens.get(name);
    if (!token) throw new Error(`Missing --${name}.`);
    return hslToHex(token);
  });
}

function adjacentWorst(colors: readonly string[], measure: (a: string, b: string) => number) {
  let worst = Infinity;
  for (let index = 0; index < colors.length - 1; index += 1) {
    worst = Math.min(worst, measure(colors[index], colors[index + 1]));
  }
  return worst;
}

function expectFamily(colors: readonly string[], mode: 'light' | 'dark', surface: string) {
  const [minL, maxL] = BAND[mode];
  for (const color of colors) {
    const { L, C } = oklch(color);
    expect(L, `${color} lightness`).toBeGreaterThanOrEqual(minL);
    expect(L, `${color} lightness`).toBeLessThanOrEqual(maxL);
    expect(C, `${color} chroma`).toBeGreaterThanOrEqual(CHROMA_FLOOR);
    expect(contrast(color, surface), `${color} contrast`).toBeGreaterThanOrEqual(CONTRAST_MIN);
  }
  expect(adjacentWorst(colors, cvdDeltaE), `${mode} adjacent CVD`).toBeGreaterThanOrEqual(CVD_TARGET);
  expect(adjacentWorst(colors, (a, b) => deltaE(a, b)), `${mode} adjacent normal`).toBeGreaterThanOrEqual(
    NORMAL_FLOOR,
  );
}

describe('chart palette validation', () => {
  it('keeps every light series family inside the validated band and floors', () => {
    expectFamily(family(light, MODEL_ORDER), 'light', LIGHT_SURFACE);
    expectFamily(family(light, INDICATOR_ORDER), 'light', LIGHT_SURFACE);
    expectFamily(family(light, ENTITY_ORDER), 'light', LIGHT_SURFACE);
  });

  it('keeps every dark series family in the dark lightness band with adjacent separation', () => {
    expectFamily(family(dark, MODEL_ORDER), 'dark', DARK_SURFACE);
    expectFamily(family(dark, INDICATOR_ORDER), 'dark', DARK_SURFACE);
    expectFamily(family(dark, ENTITY_ORDER), 'dark', DARK_SURFACE);
  });

  it('keeps model, indicator, entity and status identities distinct per mode', () => {
    for (const tokens of [light, dark]) {
      const model = family(tokens, MODEL_ORDER);
      const indicator = family(tokens, INDICATOR_ORDER);
      const entity = family(tokens, ENTITY_ORDER);
      const status = family(tokens, STATUS_ORDER);
      const all = [...model, ...indicator, ...entity];
      expect(new Set(all).size).toBe(all.length);
      for (const indicatorColor of indicator) {
        for (const other of [...model, ...entity, ...status]) {
          expect(deltaE(indicatorColor, other), `${indicatorColor}/${other}`).toBeGreaterThanOrEqual(9);
        }
      }
    }
  });
});
