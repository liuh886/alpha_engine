import { afterEach, describe, expect, it, vi } from 'vitest';
import { chartTheme } from './chart-theme';

const tokens = (values: Record<string, string>) => {
  vi.spyOn(window, 'getComputedStyle').mockReturnValue({
    getPropertyValue: (name: string) => values[name] ?? '',
  } as CSSStyleDeclaration);
};

describe('chart theme', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('converts space-separated semantic HSL tokens into canvas colors', () => {
    tokens({
      '--chart-axis': '215 16% 47%',
      '--chart-grid': '215 20% 91%',
      '--border': '215 20% 88%',
      '--chart-1': '210 90% 40%',
      '--chart-2': '173 85% 27%',
      '--positive': '152 62% 28%',
      '--negative': '0 68% 43%',
    });
    const theme = chartTheme(false);
    expect(theme.text).toBe('hsl(215, 16%, 47%)');
    expect(theme.grid).toBe('hsl(215, 20%, 91%)');
    expect(theme.border).toBe('hsl(215, 20%, 88%)');
    expect(theme.crosshair).toBe('hsl(215, 16%, 47%)');
    expect(theme.primary).toBe('hsl(210, 90%, 40%)');
    expect(theme.baseline).toBe('hsl(173, 85%, 27%)');
    expect(theme.candleUp).toBe('hsl(152, 62%, 28%)');
    expect(theme.candleDown).toBe('hsl(0, 68%, 43%)');
    expect(theme.volumeUp).toBe('hsla(152, 62%, 28%, 0.4)');
    expect(theme.volumeDown).toBe('hsla(0, 68%, 43%, 0.4)');
    expect(theme.positive).toBe(theme.candleUp);
    expect(theme.negative).toBe(theme.candleDown);
  });

  it('accepts comma-separated token components unchanged', () => {
    tokens({ '--chart-1': '210, 90%, 40%' });
    expect(chartTheme(true).primary).toBe('hsl(210, 90%, 40%)');
  });

  it('falls back to mode-appropriate canvas colors when tokens are unavailable', () => {
    tokens({});
    const light = chartTheme(false);
    const dark = chartTheme(true);
    for (const value of Object.values(light)) expect(value).toMatch(/^(hsl|rgba|#)/);
    for (const value of Object.values(dark)) expect(value).toMatch(/^(hsl|rgba|#)/);
    expect(dark.text).not.toBe(light.text);
    expect(dark.primary).not.toBe(light.primary);
    expect(dark.candleUp).not.toBe(light.candleUp);
  });

  it('uses a translucent fallback for volume when the token is missing', () => {
    tokens({});
    expect(chartTheme(false).volumeUp).toMatch(/^rgba\(/);
    expect(chartTheme(true).volumeDown).toMatch(/^rgba\(/);
  });
});
