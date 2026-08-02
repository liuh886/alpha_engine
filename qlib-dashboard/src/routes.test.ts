import { describe, expect, it } from 'vitest';
import {
  VIEW_TITLES,
  groupRoutes,
  isRuntimeVisible,
  routes,
  visibleRoutes,
  type NavGroupTitle,
  type ReleaseLevel,
  type RouteSurface,
} from './routes';

const ALL_RELEASE_LEVELS: ReleaseLevel[] = ['release', 'experimental', 'internal'];
const ALL_NAV_GROUPS: NavGroupTitle[] = ['Library', 'Evidence', 'Reference', 'Developer'];
const ALL_SURFACES: RouteSurface[] = ['artifact', 'connected', 'both'];

describe('route registry', () => {
  it('has unique paths and complete labels', () => {
    expect(routes.length).toBeGreaterThan(0);
    expect(new Set(routes.map((route) => route.path)).size).toBe(routes.length);
    for (const route of routes) {
      expect(route.title.trim()).not.toBe('');
      expect(route.label.trim()).not.toBe('');
      expect(route.icon).toBeTruthy();
      expect(ALL_RELEASE_LEVELS).toContain(route.releaseLevel);
      expect(ALL_NAV_GROUPS).toContain(route.navGroup);
      expect(ALL_SURFACES).toContain(route.surface);
      expect(VIEW_TITLES[route.path]).toBe(route.title);
      expect(route.path.startsWith('/')).toBe(false);
    }
  });

  it('covers the complete research information architecture', () => {
    const groups = new Set(routes.map((route) => route.navGroup));
    ALL_NAV_GROUPS.forEach((group) => expect(groups).toContain(group));
    expect(routes.find((route) => route.path === '')?.navGroup).toBe('Library');
    expect(routes.find((route) => route.path === 'library')?.surface).toBe('artifact');
    expect(routes.find((route) => route.path === 'system')?.surface).toBe('connected');
  });

  it('groups only routes visible in the current runtime', () => {
    const groups = groupRoutes();
    for (const [group, rows] of groups) {
      expect(ALL_NAV_GROUPS).toContain(group);
      for (const route of rows) {
        expect(route.navGroup).toBe(group);
        expect(isRuntimeVisible(route)).toBe(true);
      }
    }
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

  it('excludes internal routes unless operator mode is enabled', () => {
    expect(visibleRoutes(false).every((route) => route.releaseLevel !== 'internal')).toBe(true);
    expect(visibleRoutes(true).every((route) => isRuntimeVisible(route))).toBe(true);
  });

  it('keeps static artifact navigation free of connected-only routes', () => {
    const visible = visibleRoutes(true);
    if (!visible.some((route) => route.surface === 'connected')) {
      expect(visible.every((route) => route.surface === 'artifact' || route.surface === 'both')).toBe(true);
    }
  });
});
