import { Activity, FlaskConical, LayoutDashboard, ListTree, Settings2 } from 'lucide-react';
import { lazy, type ComponentType } from 'react';

export type NavGroupTitle = 'Workspace' | 'Operations';
export interface RouteDefinition {
  path: string; title: string; label: string;
  icon: ComponentType<{ className?: string }>;
  component: ComponentType; navVisible?: boolean;
}
const Today = lazy(() => import('./pages/StrategyOverviewPage').then(m => ({ default: m.StrategyOverviewPage })));
const Strategies = lazy(() => import('./pages/StrategiesPage').then(m => ({ default: m.StrategiesPage })));
const Strategy = lazy(() => import('./pages/StrategyDetailPage').then(m => ({ default: m.StrategyDetailPage })));
const Security = lazy(() => import('./pages/SecurityDetailPage').then(m => ({ default: m.SecurityDetailPage })));
const Research = lazy(() => import('./pages/ResearchHubPage').then(m => ({ default: m.ResearchHubPage })));
const System = lazy(() => import('./pages/SystemHubPage').then(m => ({ default: m.SystemHubPage }));

export const routes: RouteDefinition[] = [
  { path: 'app', title: 'Today', label: 'Today', icon: LayoutDashboard, component: Today },
  { path: 'strategies', title: 'Formal Strategies', label: 'Strategies', icon: ListTree, component: Strategies },
  { path: 'strategies/:strategyId', title: 'Strategy Evidence', label: 'Strategy', icon: Activity, component: Strategy, navVisible: false },
  { path: 'securities/:market/:symbol', title: 'Instrument Evidence', label: 'Instrument', icon: Activity, component: Security, navVisible: false },
  { path: 'research', title: 'Research Lab', label: 'Research', icon: FlaskConical, component: Research },
  { path: 'system', title: 'Operating Status', label: 'System', icon: Settings2, component: System },
];
export const isRuntimeVisible = (route: RouteDefinition) => route.navVisible !== false;
export function groupRoutes(): Map<NavGroupTitle, RouteDefinition[]> {
  return new Map([
    ['Workspace', routes.filter(route => isRuntimeVisible(route) && route.path !== 'system')],
    ['Operations', routes.filter(route => isRuntimeVisible(route) && route.path === 'system')],
  ]);
}
