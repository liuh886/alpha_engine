import { describe, expect, it } from 'vitest';
import { groupRoutes, isRuntimeVisible, routes } from './routes';
describe('focused daily console routes', () => {
  it('keeps the daily view, strategy drill-down and operating status', () => {
    expect(routes.map(route => route.path)).toEqual(['app', 'strategies/:strategyId', 'system']);
    expect(new Set(routes.map(route => route.path)).size).toBe(routes.length);
    for (const route of routes) expect(route.title && route.label && route.icon && route.component).toBeTruthy();
  });
  it('exposes only the two primary destinations', () => {
    expect(routes.filter(isRuntimeVisible).map(route => route.path)).toEqual(['app', 'system']);
    expect([...groupRoutes().values()].flat()).toEqual(routes.filter(isRuntimeVisible));
  });
});
