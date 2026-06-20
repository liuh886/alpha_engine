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

export type NavGroupTitle = 'Core' | 'Research' | 'Strategy' | 'System';

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
}

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

export const routes: RouteDefinition[] = [
  // -- Core ----------------------------------------------------------------
  { path: '',            title: 'Dashboard',       label: 'Dashboard',       releaseLevel: 'release',      navGroup: 'Core',      icon: LayoutDashboard },
  { path: 'terminal',    title: 'Stock Terminal',   label: 'Stock Terminal',  releaseLevel: 'experimental', navGroup: 'Core',      icon: Terminal },
  { path: 'backtest',    title: 'Backtest',         label: 'Backtest',        releaseLevel: 'release',      navGroup: 'Core',      icon: FlaskConical },

  // -- Research ------------------------------------------------------------
  { path: 'models',          title: 'Model Registry',    label: 'Models',           releaseLevel: 'release',      navGroup: 'Research',  icon: Cpu },
  { path: 'factors',         title: 'Factor Analysis',   label: 'Factor Analysis',  releaseLevel: 'release',      navGroup: 'Research',  icon: BarChart3 },
  { path: 'factor-registry', title: 'Factor Registry',   label: 'Factor Registry',  releaseLevel: 'experimental', navGroup: 'Research',  icon: ListChecks },
  { path: 'experiments',     title: 'Experiments',       label: 'Experiments',      releaseLevel: 'experimental', navGroup: 'Research',  icon: ClipboardList },
  { path: 'attribution',     title: 'Factor Attribution', label: 'Attribution',     releaseLevel: 'experimental', navGroup: 'Research',  icon: PieChart },
  { path: 'compare',         title: 'Compare',           label: 'Compare',          releaseLevel: 'release',      navGroup: 'Research',  icon: Layers },

  // -- Strategy ------------------------------------------------------------
  { path: 'arena',     title: 'Arena',         label: 'Arena',         releaseLevel: 'experimental', navGroup: 'Strategy',  icon: Swords },
  { path: 'strategy',  title: 'Strategy Spec', label: 'Strategy Spec', releaseLevel: 'experimental', navGroup: 'Strategy',  icon: Settings },
  { path: 'reports',   title: 'Reports',       label: 'Reports',       releaseLevel: 'release',      navGroup: 'Strategy',  icon: ScrollText },

  // -- System --------------------------------------------------------------
  { path: 'system',      title: 'System Monitor', label: 'System Monitor', releaseLevel: 'internal',     navGroup: 'System',    icon: Activity },
  { path: 'data',        title: 'Data Management', label: 'Data',         releaseLevel: 'release',      navGroup: 'System',    icon: Database },
  { path: 'agent',       title: 'Agent Center',   label: 'Agent Center',   releaseLevel: 'internal',     navGroup: 'System',    icon: Bot },
  { path: 'methodology', title: 'Methodology',    label: 'Methodology',    releaseLevel: 'experimental', navGroup: 'System',    icon: BookOpen },
  { path: 'docs',        title: 'Docs',           label: 'Docs',           releaseLevel: 'release',      navGroup: 'System',    icon: FileText },
];

// ---------------------------------------------------------------------------
// Derived helpers
// ---------------------------------------------------------------------------

/** Map from path to title — used by the header bar. */
export const VIEW_TITLES: Record<string, string> = {
  ...Object.fromEntries(routes.map((r) => [r.path, r.title])),
  // Legacy alias: /dashboard renders the same view as /
  dashboard: 'Dashboard',
};

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
