import { Activity, LayoutDashboard } from 'lucide-react';
import { lazy, type ComponentType } from 'react';

export type NavGroupTitle = 'Monitor';
export interface RouteDefinition {
  path: string;
  title: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  component: ComponentType;
  navVisible?: boolean;
}
const Overview = lazy(() => import('./pages/StrategyOverviewPage').then(m => ({ default: m.StrategyOverviewPage })));
const Strategy = lazy(() => import('./pages/StrategyDetailPage').then(m => ({ default: m.StrategyDetailPage })));
const System = lazy(() => import('./pages/SystemHubPage').then(m => ({ default: m.SystemHubPage })));

export const routes: RouteDefinition[] = [
  { path: 'app', title: 'Daily Research', label: 'Overview', icon: LayoutDashboard, component: Overview },
  { path: 'strategies/:strategyId', title: 'Strategy Evidence', label: 'Strategy', icon: Activity, component: Strategy, navVisible: false },
  { path: 'system', title: 'Operating Status', label: 'Status', icon: Activity, component: System },
];
export const isRuntimeVisible = (route: RouteDefinition) => route.navVisible !== false;
export function groupRoutes(): Map<NavGroupTitle, RouteDefinition[]> {
  return new Map([['Monitor', routes.filter(isRuntimeVisible)]]);
}
