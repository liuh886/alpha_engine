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
const ALL_NAV_GROUPS: NavGroupTitle[] = ['Workspace', 'Evidence', 'Reference'];

describe('artifact-only route registry', () => {
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

  it('covers the governed artifact information architecture', () => {
    const visible = visibleRoutes(false);
    const groups = new Set(visible.map((route) => route.navGroup));
    ALL_NAV_GROUPS.forEach((group) => expect(groups).toContain(group));
    expect(visible.find((route) => route.path === '')?.navGroup).toBe('Workspace');
    expect(visible.find((route) => route.path === 'runs')?.navGroup).toBe('Workspace');
    expect(visible.find((route) => route.path === 'review')?.navGroup).toBe('Workspace');
    expect(visible.find((route) => route.path === 'decisions')?.navGroup).toBe('Workspace');
    expect(visible.find((route) => route.path === 'library')?.navGroup).toBe('Workspace');
    expect(routes.some((route) => route.path === 'system')).toBe(false);
    expect(routes.some((route) => route.path === 'agent')).toBe(false);
    expect(routes.some((route) => route.path === 'backtest')).toBe(false);
  });

  it('groups every navigation-visible artifact route and excludes compatibility routes', () => {
    const groups = groupRoutes();
    for (const [group, rows] of groups) {
      expect(ALL_NAV_GROUPS).toContain(group);
      for (const route of rows) {
        expect(route.navGroup).toBe(group);
        expect(isRuntimeVisible(route)).toBe(true);
      }
    }
    const grouped = Array.from(groups.values()).flat();
    expect(grouped).toEqual(routes.filter(isRuntimeVisible));
    expect(routes.filter((route) => !isRuntimeVisible(route)).map((route) => route.path)).toEqual(['dashboard', 'models']);
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
    for (const [, rows] of releaseOnly) {
      rows.forEach((route) => expect(route.releaseLevel).toBe('release'));
    }
  });

  it('returns the same navigation routes regardless of operator mode', () => {
    const expected = routes.filter(isRuntimeVisible);
    expect(visibleRoutes(false)).toEqual(expected);
    expect(visibleRoutes(true)).toEqual(expected);
  });
});
