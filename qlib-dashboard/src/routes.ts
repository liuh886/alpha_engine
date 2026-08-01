/**
 * Single source of truth for all frontend routes.
 *
 * Each route carries a `releaseLevel` drawn from docs/release/scope.md.
 * The Sidebar uses this to decide visibility; App.tsx uses it to render
 * the <Route> tree. Adding a new page = one entry here + the lazy import.
 */

import {
  LayoutDashboard,
  Terminal,
  FlaskConical,
  Cpu,
  BarChart3,
  ListChecks,
  ClipboardList,
  PieChart,
  Layers,
  Swords,
  Settings,
  ScrollText,
  Activity,
  Database,
  Bot,
  BookOpen,
  FileText,
  Radar,
} from 'lucide-react';
import type { ComponentType } from 'react';
import { runtimeCapabilities } from './lib/runtime-capabilities';

export type ReleaseLevel = 'release' | 'experimental' | 'internal';

export type NavGroupTitle = 'Daily Research' | 'Model Lab' | 'Backtest & Attribution' | 'System & Ops';

export interface RouteDefinition {
  path: string;
  title: string;
  releaseLevel: ReleaseLevel;
  navGroup: NavGroupTitle;
  requiredCapability?: string;
  icon: ComponentType<{ className?: string }>;
  label: string;
  component: ComponentType<any>;
}

import { lazy } from 'react';

const HomePage = lazy(() => import('./pages/ArtifactStudioHomePage').then(m => ({ default: m.ArtifactStudioHomePage })));
const DashboardPage = lazy(() => import('./pages/DashboardPage').then(m => ({ default: m.DashboardPage })));
const DecisionDeskPage = lazy(() => import('./pages/DecisionDeskPage').then(m => ({ default: m.DecisionDeskPage })));
const StrategyPage = lazy(() => import('./pages/StrategyPage').then(m => ({ default: m.StrategyPage })));
const ComparePage = lazy(() => import('./pages/ComparePage').then(m => ({ default: m.ComparePage })));
const ArenaPage = lazy(() => import('./pages/ArenaPage').then(m => ({ default: m.ArenaPage })));
const ReportsPage = lazy(() => import('./pages/ReportsPage').then(m => ({ default: m.ReportsPage })));
const ModelsPage = lazy(() => import('./pages/ModelsPage').then(m => ({ default: m.ModelsPage })));
const DataPage = lazy(() => import('./pages/DataPage').then(m => ({ default: m.DataPage })));
const FactorPage = lazy(() => import('./pages/FactorPage').then(m => ({ default: m.FactorPage })));
const FactorRegistryPage = lazy(() => import('./pages/FactorRegistryPage').then(m => ({ default: m.FactorRegistryPage })));
const ExperimentLogPage = lazy(() => import('./pages/ExperimentLogPage').then(m => ({ default: m.ExperimentLogPage })));
const AttributionPage = lazy(() => import('./pages/AttributionPage').then(m => ({ default: m.AttributionPage })));
const StockTerminal = lazy(() => import('./pages/StockTerminal').then(m => ({ default: m.StockTerminal })));
const AgentControlCenter = lazy(() => import('./pages/AgentControlCenter').then(m => ({ default: m.AgentControlCenter })));
const DocsPage = lazy(() => import('./pages/DocsPage').then(m => ({ default: m.DocsPage })));
const BacktestPage = lazy(() => import('./pages/BacktestPage').then(m => ({ default: m.BacktestPage })));
const MethodologyPage = lazy(() => import('./pages/MethodologyPage').then(m => ({ default: m.MethodologyPage })));
const SystemPage = lazy(() => import('./pages/SystemPage').then(m => ({ default: m.SystemPage })));
const TopBottomPage = lazy(() => import('./components/TopBottomAnalysis').then(m => ({ default: m.TopBottomAnalysis })));

export const routes: RouteDefinition[] = [
  { path: '',              title: 'Research Studio',   label: 'Home',            releaseLevel: 'release',      navGroup: 'Daily Research', icon: LayoutDashboard, component: HomePage },
  { path: 'dashboard',     title: 'Model Dashboard',   label: 'Model Dashboard', releaseLevel: 'release',      navGroup: 'Daily Research', icon: LayoutDashboard, component: DashboardPage },
  { path: 'decision-desk', title: 'Decision Desk',     label: 'Decision Desk',   releaseLevel: 'experimental', navGroup: 'Daily Research', icon: Radar, component: DecisionDeskPage },
  { path: 'terminal',      title: 'Stock Terminal',    label: 'Stock Terminal',  releaseLevel: 'experimental', navGroup: 'Daily Research', icon: Terminal, component: StockTerminal },

  { path: 'models',          title: 'Model Registry',    label: 'Models',          releaseLevel: 'release',      navGroup: 'Model Lab', icon: Cpu, component: ModelsPage },
  { path: 'factors',         title: 'Factor Analysis',   label: 'Factor Analysis', releaseLevel: 'release',      navGroup: 'Model Lab', icon: BarChart3, component: FactorPage },
  { path: 'factor-registry', title: 'Factor Registry',   label: 'Factor Registry', releaseLevel: 'experimental', navGroup: 'Model Lab', icon: ListChecks, component: FactorRegistryPage },
  { path: 'experiments',     title: 'Experiments',       label: 'Experiments',     releaseLevel: 'experimental', navGroup: 'Model Lab', icon: ClipboardList, component: ExperimentLogPage },
  { path: 'strategy',        title: 'Strategy Spec',     label: 'Strategy Spec',   releaseLevel: 'experimental', navGroup: 'Model Lab', icon: Settings, component: StrategyPage },
  { path: 'arena',           title: 'Arena',             label: 'Arena',           releaseLevel: 'experimental', navGroup: 'Model Lab', icon: Swords, component: ArenaPage },

  { path: 'backtest',    title: 'Backtest',            label: 'Backtest',            releaseLevel: 'release',      navGroup: 'Backtest & Attribution', icon: FlaskConical, component: BacktestPage },
  { path: 'top-bottom',  title: 'Top/Bottom Analysis', label: 'Top/Bottom Analysis', releaseLevel: 'experimental', navGroup: 'Backtest & Attribution', icon: BarChart3, component: TopBottomPage },
  { path: 'attribution', title: 'Factor Attribution',  label: 'Attribution',         releaseLevel: 'experimental', navGroup: 'Backtest & Attribution', icon: PieChart, component: AttributionPage },
  { path: 'compare',     title: 'Compare',             label: 'Compare',             releaseLevel: 'release',      navGroup: 'Backtest & Attribution', icon: Layers, component: ComparePage },
  { path: 'reports',     title: 'Reports',             label: 'Reports',             releaseLevel: 'release',      navGroup: 'Backtest & Attribution', icon: ScrollText, component: ReportsPage },

  { path: 'data',        title: 'Data Management', label: 'Data',           releaseLevel: 'release',      navGroup: 'System & Ops', icon: Database, component: DataPage },
  { path: 'system',      title: 'System Monitor',  label: 'System Monitor', releaseLevel: 'internal',     navGroup: 'System & Ops', icon: Activity, component: SystemPage },
  { path: 'agent',       title: 'Agent Center',    label: 'Agent Center',   releaseLevel: 'internal',     navGroup: 'System & Ops', icon: Bot, component: AgentControlCenter },
  { path: 'methodology', title: 'Methodology',     label: 'Methodology',    releaseLevel: 'experimental', navGroup: 'System & Ops', icon: BookOpen, component: MethodologyPage },
  { path: 'docs',        title: 'Docs',            label: 'Docs',           releaseLevel: 'release',      navGroup: 'System & Ops', icon: FileText, component: DocsPage },
];

const ARTIFACT_SAFE_PATHS = new Set(['', 'dashboard', 'models', 'compare', 'methodology']);

function isRuntimeVisible(route: RouteDefinition): boolean {
  return runtimeCapabilities.backendApi || ARTIFACT_SAFE_PATHS.has(route.path);
}

export const VIEW_TITLES: Record<string, string> = {
  ...Object.fromEntries(routes.map((r) => [r.path, r.title])),
};

export function navigateTo(path: string): void {
  window.location.hash = path ? `#/${path}` : '#/';
}

export function groupRoutes(filterFn?: (r: RouteDefinition) => boolean): Map<NavGroupTitle, RouteDefinition[]> {
  const groups = new Map<NavGroupTitle, RouteDefinition[]>();
  for (const r of routes) {
    if (!isRuntimeVisible(r)) continue;
    if (filterFn && !filterFn(r)) continue;
    const arr = groups.get(r.navGroup) ?? [];
    arr.push(r);
    groups.set(r.navGroup, arr);
  }
  return groups;
}

export function visibleRoutes(operatorMode: boolean): RouteDefinition[] {
  return routes.filter((r) => {
    if (!isRuntimeVisible(r)) return false;
    if (r.releaseLevel === 'internal') return operatorMode;
    return true;
  });
}
