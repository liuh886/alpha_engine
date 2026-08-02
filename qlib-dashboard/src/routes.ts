import {
  Activity,
  BarChart3,
  BookOpen,
  Cpu,
  Database,
  FolderArchive,
  Layers,
  LayoutDashboard,
  ScrollText,
} from 'lucide-react';
import { lazy, type ComponentType } from 'react';

export type ReleaseLevel = 'release' | 'experimental' | 'internal';
export type NavGroupTitle = 'Workspace' | 'Evidence' | 'Reference';

export interface RouteDefinition {
  path: string;
  title: string;
  releaseLevel: ReleaseLevel;
  navGroup: NavGroupTitle;
  icon: ComponentType<{ className?: string }>;
  label: string;
  component: ComponentType<any>;
}

const HomePage = lazy(() => import('./pages/ArtifactStudioHomePage').then((m) => ({ default: m.ArtifactStudioHomePage })));
const LibraryPage = lazy(() => import('./pages/LibraryPage').then((m) => ({ default: m.LibraryPage })));
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })));
const StrategyOperationsPage = lazy(() => import('./pages/StrategyOperationsPage').then((m) => ({ default: m.StrategyOperationsPage })));
const EvidenceModelsPage = lazy(() => import('./pages/EvidenceModelsPage').then((m) => ({ default: m.EvidenceModelsPage })));
const EvidenceDataPage = lazy(() => import('./pages/EvidenceDataPage').then((m) => ({ default: m.EvidenceDataPage })));
const EvidenceFactorsPage = lazy(() => import('./pages/EvidenceFactorsPage').then((m) => ({ default: m.EvidenceFactorsPage })));
const EvidenceReportsPage = lazy(() => import('./pages/EvidenceReportsPage').then((m) => ({ default: m.EvidenceReportsPage })));
const ComparePage = lazy(() => import('./pages/ComparePage').then((m) => ({ default: m.ComparePage })));
const MethodologyPage = lazy(() => import('./pages/MethodologyPage').then((m) => ({ default: m.MethodologyPage })));

/**
 * The Web product exposes accepted formal research artifacts and a read-only
 * operational evidence ledger. Execution, exploratory journals and mutation
 * routes remain outside the browser.
 */
export const routes: RouteDefinition[] = [
  { path: '', title: 'Research Overview', label: 'Overview', releaseLevel: 'release', navGroup: 'Workspace', icon: LayoutDashboard, component: HomePage },
  { path: 'library', title: 'Bundle Library', label: 'Library', releaseLevel: 'release', navGroup: 'Workspace', icon: FolderArchive, component: LibraryPage },
  { path: 'operations', title: 'v4.2 Operations', label: 'Operations', releaseLevel: 'release', navGroup: 'Workspace', icon: Activity, component: StrategyOperationsPage },

  { path: 'dashboard', title: 'Formal Backtest Review', label: 'Backtests', releaseLevel: 'release', navGroup: 'Evidence', icon: BarChart3, component: DashboardPage },
  { path: 'models', title: 'Model Evidence', label: 'Models', releaseLevel: 'release', navGroup: 'Evidence', icon: Cpu, component: EvidenceModelsPage },
  { path: 'compare', title: 'Formal Baseline Comparison', label: 'Compare', releaseLevel: 'release', navGroup: 'Evidence', icon: Layers, component: ComparePage },
  { path: 'data', title: 'Data Lineage', label: 'Data', releaseLevel: 'release', navGroup: 'Evidence', icon: Database, component: EvidenceDataPage },
  { path: 'factors', title: 'Factor Evidence', label: 'Factors', releaseLevel: 'release', navGroup: 'Evidence', icon: BarChart3, component: EvidenceFactorsPage },
  { path: 'reports', title: 'Reports & Notebooks', label: 'Reports', releaseLevel: 'release', navGroup: 'Evidence', icon: ScrollText, component: EvidenceReportsPage },

  { path: 'methodology', title: 'Methodology & Boundaries', label: 'Methodology', releaseLevel: 'release', navGroup: 'Reference', icon: BookOpen, component: MethodologyPage },
];

export function isRuntimeVisible(_route: RouteDefinition): boolean {
  return true;
}

export const VIEW_TITLES: Record<string, string> = Object.fromEntries(routes.map((route) => [route.path, route.title]));

export function navigateTo(path: string): void {
  window.location.hash = path ? `#/${path}` : '#/';
}

export function groupRoutes(filterFn?: (route: RouteDefinition) => boolean): Map<NavGroupTitle, RouteDefinition[]> {
  const groups = new Map<NavGroupTitle, RouteDefinition[]>();
  for (const route of routes) {
    if (filterFn && !filterFn(route)) continue;
    const rows = groups.get(route.navGroup) ?? [];
    rows.push(route);
    groups.set(route.navGroup, rows);
  }
  return groups;
}

export function visibleRoutes(_operatorMode: boolean): RouteDefinition[] {
  return routes;
}
