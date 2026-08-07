import { describe, expect, it } from 'vitest';
import {
  VIEW_TITLES,
  groupRoutes,
  isRuntimeVisible,
  routes,
  visibleRoutes,
  type NavGroupTitle,
  type ReleaseLevel,
} from './routes';

const ALL_RELEASE_LEVELS: ReleaseLevel[] = ['release', 'experimental', 'internal'];
const ALL_NAV_GROUPS: NavGroupTitle[] = ['Monitor', 'Research', 'System'];

describe('strategy-console route registry', () => {
  it('has unique paths and complete labels', () => {
    expect(routes.length).toBeGreaterThan(0);
    expect(new Set(routes.map((route) => route.path)).size).toBe(routes.length);
    for (const route of routes) {
      expect(route.title.trim()).not.toBe('');
      expect(route.label.trim()).not.toBe('');
      expect(route.icon).toBeTruthy();
      expect(ALL_RELEASE_LEVELS).toContain(route.releaseLevel);
      expect(ALL_NAV_GROUPS).toContain(route.navGroup);
      expect(VIEW_TITLES[route.path]).toBe(route.title);
      expect(route.path.startsWith('/')).toBe(false);
    }
  });

  it('exposes only the four product-level navigation destinations', () => {
    const visible = visibleRoutes(false);
    expect(visible.map((route) => route.path)).toEqual(['app', 'strategies', 'research', 'system']);
    expect(visible.map((route) => route.label)).toEqual(['Overview', 'Strategies', 'Research', 'System']);
    const groups = new Set(visible.map((route) => route.navGroup));
    ALL_NAV_GROUPS.forEach((group) => expect(groups).toContain(group));
  });

  it('keeps evidence tools as drill-down routes rather than primary navigation', () => {
    for (const path of ['runs', 'backtests', 'review', 'compare', 'decisions', 'factors', 'reports', 'data', 'library', 'methodology', 'strategies/:strategyId']) {
      expect(routes.find((route) => route.path === path)?.navVisible).toBe(false);
    }
    for (const removed of ['operations', 'dashboard', 'models', 'agent', 'backtest']) {
      expect(routes.some((route) => route.path === removed)).toBe(false);
    }
  });

  it('groups every navigation-visible route and excludes drill-down views', () => {
    const groups = groupRoutes();
    for (const [group, rows] of groups) {
      expect(ALL_NAV_GROUPS).toContain(group);
      rows.forEach((route) => {
        expect(route.navGroup).toBe(group);
        expect(isRuntimeVisible(route)).toBe(true);
      });
    }
    expect(Array.from(groups.values()).flat()).toEqual(routes.filter(isRuntimeVisible));
  });

  it('preserves route declaration order within groups', () => {
    const grouped = groupRoutes();
    for (const [, rows] of grouped) {
      const positions = rows.map((route) => routes.indexOf(route));
      expect(positions).toEqual([...positions].sort((a, b) => a - b));
    }
  });

  it('supports filtered grouping', () => {
    const releaseOnly = groupRoutes((route) => route.releaseLevel === 'release');
    for (const [, rows] of releaseOnly) rows.forEach((route) => expect(route.releaseLevel).toBe('release'));
  });

  it('returns the same product navigation regardless of operator mode', () => {
    expect(visibleRoutes(false)).toEqual(routes.filter(isRuntimeVisible));
    expect(visibleRoutes(true)).toEqual(routes.filter(isRuntimeVisible));
  });
});
