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

  it('covers the complete artifact information architecture', () => {
    const groups = new Set(routes.map((route) => route.navGroup));
    ALL_NAV_GROUPS.forEach((group) => expect(groups).toContain(group));
    expect(routes.find((route) => route.path === '')?.navGroup).toBe('Workspace');
    expect(routes.find((route) => route.path === 'library')?.navGroup).toBe('Workspace');
    expect(routes.some((route) => route.path === 'system')).toBe(false);
    expect(routes.some((route) => route.path === 'agent')).toBe(false);
    expect(routes.some((route) => route.path === 'backtest')).toBe(false);
  });

  it('groups every declared artifact route', () => {
    const groups = groupRoutes();
    for (const [group, rows] of groups) {
      expect(ALL_NAV_GROUPS).toContain(group);
      for (const route of rows) {
        expect(route.navGroup).toBe(group);
        expect(isRuntimeVisible(route)).toBe(true);
      }
    }
    expect(Array.from(groups.values()).flat()).toHaveLength(routes.length);
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

  it('returns the same artifact routes regardless of operator mode', () => {
    expect(visibleRoutes(false)).toEqual(routes);
    expect(visibleRoutes(true)).toEqual(routes);
  });
});
