import { describe, expect, it } from 'vitest';
import { groupRoutes, isRuntimeVisible, routes } from './routes';
describe('Decision-first workspace routes', () => {
  it('preserves strategy and instrument deep links while separating independent research', () => {
    expect(routes.map(route => route.path)).toEqual([
      'app', 'strategies', 'strategies/:strategyId', 'securities/:market/:symbol', 'research', 'system',
    ]);
    expect(new Set(routes.map(route => route.path)).size).toBe(routes.length);
    for (const route of routes) expect(route.title && route.label && route.icon && route.component).toBeTruthy();
  });
  it('groups research jobs and system operations separately', () => {
    expect(routes.filter(isRuntimeVisible).map(route => route.path)).toEqual(['app', 'strategies', 'research', 'system']);
    const groups = groupRoutes();
    expect(groups.get('Workspace')?.map(route => route.path)).toEqual(['app', 'strategies', 'research']);
    expect(groups.get('Operations')?.map(route => route.path)).toEqual(['system']);
    expect([...groups.values()].flat()).toEqual(routes.filter(isRuntimeVisible));
  });
});
