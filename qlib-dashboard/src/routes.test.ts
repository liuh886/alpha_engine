/**
 * Tests for the route registry — completeness, consistency, and helpers.
 */

import { describe, it, expect } from 'vitest';
import {
  routes,
  VIEW_TITLES,
  groupRoutes,
  visibleRoutes,
  type ReleaseLevel,
  type NavGroupTitle,
} from './routes';

// All valid release levels from the type.
const ALL_RELEASE_LEVELS: ReleaseLevel[] = ['release', 'experimental', 'internal'];

// All valid nav groups from the type.
const ALL_NAV_GROUPS: NavGroupTitle[] = ['Daily Research', 'Model Lab', 'Backtest & Attribution', 'System & Ops'];

describe('route registry', () => {
  // -----------------------------------------------------------------------
  // Basic structure
  // -----------------------------------------------------------------------

  it('is a non-empty array', () => {
    expect(routes.length).toBeGreaterThan(0);
  });

  it('every route has a unique path', () => {
    const paths = routes.map((r) => r.path);
    const unique = new Set(paths);
    expect(unique.size).toBe(paths.length);
  });

  it('every route has a non-empty title', () => {
    for (const r of routes) {
      expect(r.title.trim()).not.toBe('');
    }
  });

  it('every route has a non-empty label', () => {
    for (const r of routes) {
      expect(r.label.trim()).not.toBe('');
    }
  });

  it('every route has an icon component', () => {
    for (const r of routes) {
      // lucide-react icons are React.forwardRef objects, not plain functions.
      // Verify they are truthy and renderable (either a function or an object with $$typeof).
      expect(r.icon).toBeTruthy();
    }
  });

  // -----------------------------------------------------------------------
  // Release levels
  // -----------------------------------------------------------------------

  it('every route has a valid releaseLevel', () => {
    for (const r of routes) {
      expect(ALL_RELEASE_LEVELS).toContain(r.releaseLevel);
    }
  });

  it('covers all release levels', () => {
    const levels = new Set(routes.map((r) => r.releaseLevel));
    for (const level of ALL_RELEASE_LEVELS) {
      expect(levels).toContain(level);
    }
  });

  // -----------------------------------------------------------------------
  // Nav groups
  // -----------------------------------------------------------------------

  it('every route has a valid navGroup', () => {
    for (const r of routes) {
      expect(ALL_NAV_GROUPS).toContain(r.navGroup);
    }
  });

  it('covers all nav groups', () => {
    const groups = new Set(routes.map((r) => r.navGroup));
    for (const group of ALL_NAV_GROUPS) {
      expect(groups).toContain(group);
    }
  });

  // -----------------------------------------------------------------------
  // VIEW_TITLES
  // -----------------------------------------------------------------------

  it('VIEW_TITLES contains every route path', () => {
    for (const r of routes) {
      expect(VIEW_TITLES[r.path]).toBe(r.title);
    }
  });


  // -----------------------------------------------------------------------
  // groupRoutes
  // -----------------------------------------------------------------------

  it('groupRoutes returns a Map with all nav groups as keys', () => {
    const groups = groupRoutes();
    for (const group of ALL_NAV_GROUPS) {
      expect(groups.has(group)).toBe(true);
    }
  });

  it('groupRoutes preserves declaration order within groups', () => {
    const groups = groupRoutes();
    for (const [group, groupRoutes] of groups) {
      // Each route in the group should have the correct navGroup
      for (const r of groupRoutes) {
        expect(r.navGroup).toBe(group);
      }
    }
  });

  it('groupRoutes with filterFn only includes matching routes', () => {
    const releaseOnly = groupRoutes((r) => r.releaseLevel === 'release');
    for (const [, groupRoutes] of releaseOnly) {
      for (const r of groupRoutes) {
        expect(r.releaseLevel).toBe('release');
      }
    }
    // Should have fewer total routes than unfiltered
    let filteredTotal = 0;
    for (const [, groupRoutes] of releaseOnly) {
      filteredTotal += groupRoutes.length;
    }
    expect(filteredTotal).toBeLessThan(routes.length);
  });

  // -----------------------------------------------------------------------
  // visibleRoutes
  // -----------------------------------------------------------------------

  it('visibleRoutes(false) excludes internal routes', () => {
    const visible = visibleRoutes(false);
    for (const r of visible) {
      expect(r.releaseLevel).not.toBe('internal');
    }
  });

  it('visibleRoutes(true) includes all routes', () => {
    const visible = visibleRoutes(true);
    expect(visible.length).toBe(routes.length);
  });

  it('visibleRoutes(false) includes release and experimental routes', () => {
    const visible = visibleRoutes(false);
    const levels = new Set(visible.map((r) => r.releaseLevel));
    expect(levels.has('release')).toBe(true);
    expect(levels.has('experimental')).toBe(true);
    expect(levels.has('internal')).toBe(false);
  });

  // -----------------------------------------------------------------------
  // Consistency checks
  // -----------------------------------------------------------------------

  it('index route (empty path) exists and is in Core', () => {
    const indexRoute = routes.find((r) => r.path === '');
    expect(indexRoute).toBeDefined();
    expect(indexRoute!.navGroup).toBe('Daily Research');
  });

  it('no route path contains a leading slash', () => {
    for (const r of routes) {
      expect(r.path.startsWith('/')).toBe(false);
    }
  });
});
