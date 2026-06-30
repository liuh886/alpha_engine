/**
 * Single source of truth for all frontend routes.
 *
 * Each route carries a `releaseLevel` drawn from docs/release/scope.md.
 * The Sidebar uses this to decide visibility; App.tsx uses it to render
 * the <Route> tree.  Adding a new page = one entry here + the lazy import
 * in App.tsx.
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
} from 'lucide-react';
import type { ComponentType } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ReleaseLevel = 'release' | 'experimental' | 'internal';

export type NavGroupTitle = 'Daily Research' | 'Model Lab' | 'Backtest & Attribution' | 'System & Ops';

export interface RouteDefinition {
  /** Hash-router path (without leading `/`; empty string = index). */
  path: string;
  /** Human-readable title shown in the header bar. */
  title: string;
  /** Release classification from docs/release/scope.md. */
  releaseLevel: ReleaseLevel;
  /** Which sidebar section this route belongs to. */
  navGroup: NavGroupTitle;
  /** Optional capability key for fine-grained gating (future use). */
  requiredCapability?: string;
  /** Sidebar icon. */
  icon: ComponentType<{ className?: string }>;
  /** Sidebar label. */
  label: string;
  /** React Component. */
  component: ComponentType<any>;
}

import { lazy } from 'react';

// Lazy-loaded pages (code splitting)
const HomePage = lazy(() => import('./pages/HomePage').then(m => ({ default: m.HomePage })));
const DashboardPage = lazy(() => import('./pages/DashboardPage').then(m => ({ default: m.DashboardPage })));
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

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

export const routes: RouteDefinition[] = [
  // -- Daily Research --------------------------------------------------------
  { path: '',            title: 'System Home',     label: 'Home',            releaseLevel: 'release',      navGroup: 'Daily Research',      icon: LayoutDashboard, component: HomePage },
  { path: 'dashboard',   title: 'Model Dashboard', label: 'Model Dashboard', releaseLevel: 'release',      navGroup: 'Daily Research',      icon: LayoutDashboard, component: DashboardPage },
  { path: 'terminal',    title: 'Stock Terminal',   label: 'Stock Terminal',  releaseLevel: 'experimental', navGroup: 'Daily Research',      icon: Terminal, component: StockTerminal },

  // -- Model Lab -------------------------------------------------------------
  { path: 'models',          title: 'Model Registry',    label: 'Models',           releaseLevel: 'release',      navGroup: 'Model Lab',  icon: Cpu, component: ModelsPage },
  { path: 'factors',         title: 'Factor Analysis',   label: 'Factor Analysis',  releaseLevel: 'release',      navGroup: 'Model Lab',  icon: BarChart3, component: FactorPage },
  { path: 'factor-registry', title: 'Factor Registry',   label: 'Factor Registry',  releaseLevel: 'experimental', navGroup: 'Model Lab',  icon: ListChecks, component: FactorRegistryPage },
  { path: 'experiments',     title: 'Experiments',       label: 'Experiments',      releaseLevel: 'experimental', navGroup: 'Model Lab',  icon: ClipboardList, component: ExperimentLogPage },
  { path: 'strategy',  title: 'Strategy Spec', label: 'Strategy Spec', releaseLevel: 'experimental', navGroup: 'Model Lab',  icon: Settings, component: StrategyPage },
  { path: 'arena',     title: 'Arena',         label: 'Arena',         releaseLevel: 'experimental', navGroup: 'Model Lab',  icon: Swords, component: ArenaPage },

  // -- Backtest & Attribution ------------------------------------------------
  { path: 'backtest',    title: 'Backtest',         label: 'Backtest',        releaseLevel: 'release',      navGroup: 'Backtest & Attribution',      icon: FlaskConical, component: BacktestPage },
  { path: 'top-bottom',  title: 'Top/Bottom Analysis', label: 'Top/Bottom Analysis', releaseLevel: 'experimental', navGroup: 'Backtest & Attribution', icon: BarChart3, component: TopBottomPage },
  { path: 'attribution',     title: 'Factor Attribution', label: 'Attribution',     releaseLevel: 'experimental', navGroup: 'Backtest & Attribution',  icon: PieChart, component: AttributionPage },
  { path: 'compare',         title: 'Compare',           label: 'Compare',          releaseLevel: 'release',      navGroup: 'Backtest & Attribution',  icon: Layers, component: ComparePage },
  { path: 'reports',   title: 'Reports',       label: 'Reports',       releaseLevel: 'release',      navGroup: 'Backtest & Attribution',  icon: ScrollText, component: ReportsPage },

  // -- System & Ops ----------------------------------------------------------
  { path: 'data',        title: 'Data Management', label: 'Data',         releaseLevel: 'release',      navGroup: 'System & Ops',    icon: Database, component: DataPage },
  { path: 'system',      title: 'System Monitor', label: 'System Monitor', releaseLevel: 'internal',     navGroup: 'System & Ops',    icon: Activity, component: SystemPage },
  { path: 'agent',       title: 'Agent Center',   label: 'Agent Center',   releaseLevel: 'internal',     navGroup: 'System & Ops',    icon: Bot, component: AgentControlCenter },
  { path: 'methodology', title: 'Methodology',    label: 'Methodology',    releaseLevel: 'experimental', navGroup: 'System & Ops',    icon: BookOpen, component: MethodologyPage },
  { path: 'docs',        title: 'Docs',           label: 'Docs',           releaseLevel: 'release',      navGroup: 'System & Ops',    icon: FileText, component: DocsPage },
];

// ---------------------------------------------------------------------------
// Derived helpers
// ---------------------------------------------------------------------------

/** Map from path to title — used by the header bar. */
export const VIEW_TITLES: Record<string, string> = {
  ...Object.fromEntries(routes.map((r) => [r.path, r.title])),
};

/**
 * Navigate to an internal hash route.
 *
 * This is the single place that writes `window.location.hash`.
 * Components must never mutate the hash directly — import this helper instead.
 *
 * @example
 *   import { navigateTo } from '@/routes';
 *   navigateTo('backtest');  // → #/backtest
 */
export function navigateTo(path: string): void {
  window.location.hash = path ? `#/${path}` : '#/';
}

/** Group routes by navGroup, preserving declaration order. */
export function groupRoutes(filterFn?: (r: RouteDefinition) => boolean): Map<NavGroupTitle, RouteDefinition[]> {
  const groups = new Map<NavGroupTitle, RouteDefinition[]>();
  for (const r of routes) {
    if (filterFn && !filterFn(r)) continue;
    const arr = groups.get(r.navGroup) ?? [];
    arr.push(r);
    groups.set(r.navGroup, arr);
  }
  return groups;
}

/** Convenience: routes that should appear for a given operator-mode setting. */
export function visibleRoutes(operatorMode: boolean): RouteDefinition[] {
  return routes.filter((r) => {
    if (r.releaseLevel === 'internal') return operatorMode;
    return true;
  });
}
