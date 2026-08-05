import {
  Activity,
  BarChart3,
  BookOpen,
  Database,
  FileCheck2,
  FolderArchive,
  GitCompareArrows,
  LayoutDashboard,
  ListTree,
  ScrollText,
  ShieldQuestion,
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
  navVisible?: boolean;
}

const HomePage = lazy(() => import('./pages/ArtifactStudioHomePage').then((m) => ({ default: m.ArtifactStudioHomePage })));
const LibraryPage = lazy(() => import('./pages/LibraryPage').then((m) => ({ default: m.LibraryPage })));
const RunsPage = lazy(() => import('./pages/RunsPage').then((m) => ({ default: m.RunsPage })));
const FormalBacktestsPage = lazy(() => import('./pages/FormalBacktestsPage').then((m) => ({ default: m.FormalBacktestsPage })));
const RunReviewPage = lazy(() => import('./pages/RunReviewPage').then((m) => ({ default: m.RunReviewPage })));
const StrategyOperationsPage = lazy(() => import('./pages/StrategyOperationsPage').then((m) => ({ default: m.StrategyOperationsPage })));
const EvidenceDataPage = lazy(() => import('./pages/EvidenceDataPage').then((m) => ({ default: m.EvidenceDataPage })));
const EvidenceFactorsPage = lazy(() => import('./pages/EvidenceFactorsPage').then((m) => ({ default: m.EvidenceFactorsPage })));
const EvidenceReportsPage = lazy(() => import('./pages/EvidenceReportsPage').then((m) => ({ default: m.EvidenceReportsPage })));
const ComparePage = lazy(() => import('./pages/ComparePage').then((m) => ({ default: m.ComparePage })));
const DecisionsPage = lazy(() => import('./pages/DecisionsPage').then((m) => ({ default: m.DecisionsPage })));
const MethodologyPage = lazy(() => import('./pages/MethodologyPage').then((m) => ({ default: m.MethodologyPage })));
const LegacyDashboardRedirect = lazy(() => import('./pages/LegacyDashboardRedirect').then((m) => ({ default: m.LegacyDashboardRedirect })));

/** Static, read-only research navigation after the formal Bundle v2 cutover. */
export const routes: RouteDefinition[] = [
  { path: 'app', title: 'Research Overview', label: 'Overview', releaseLevel: 'release', navGroup: 'Workspace', icon: LayoutDashboard, component: HomePage },
  { path: 'runs', title: 'Governed Model Runs', label: 'Runs', releaseLevel: 'release', navGroup: 'Workspace', icon: ListTree, component: RunsPage },
  { path: 'backtests', title: 'Formal Backtests', label: 'Backtests', releaseLevel: 'release', navGroup: 'Workspace', icon: BarChart3, component: FormalBacktestsPage },
  { path: 'review', title: 'Run Review', label: 'Review', releaseLevel: 'release', navGroup: 'Workspace', icon: FileCheck2, component: RunReviewPage },
  { path: 'compare', title: 'Compatible Run Comparison', label: 'Compare', releaseLevel: 'release', navGroup: 'Workspace', icon: GitCompareArrows, component: ComparePage },
  { path: 'decisions', title: 'Research Decisions', label: 'Decisions', releaseLevel: 'release', navGroup: 'Workspace', icon: ShieldQuestion, component: DecisionsPage },
  { path: 'library', title: 'Local Bundle Library', label: 'Library', releaseLevel: 'release', navGroup: 'Workspace', icon: FolderArchive, component: LibraryPage },

  { path: 'operations', title: 'v4.2 Operations', label: 'Operations', releaseLevel: 'release', navGroup: 'Evidence', icon: Activity, component: StrategyOperationsPage },
  { path: 'data', title: 'Data Lineage', label: 'Data', releaseLevel: 'release', navGroup: 'Evidence', icon: Database, component: EvidenceDataPage },
  { path: 'factors', title: 'Factor Evidence', label: 'Factors', releaseLevel: 'release', navGroup: 'Evidence', icon: BarChart3, component: EvidenceFactorsPage },
  { path: 'reports', title: 'Reports & Notebooks', label: 'Reports', releaseLevel: 'release', navGroup: 'Evidence', icon: ScrollText, component: EvidenceReportsPage },

  { path: 'methodology', title: 'Methodology & Boundaries', label: 'Methodology', releaseLevel: 'release', navGroup: 'Reference', icon: BookOpen, component: MethodologyPage },

  { path: 'dashboard', title: 'Formal Backtests', label: 'Backtests', releaseLevel: 'internal', navGroup: 'Workspace', icon: BarChart3, component: LegacyDashboardRedirect, navVisible: false },
];

export function isRuntimeVisible(route: RouteDefinition): boolean {
  return route.navVisible !== false;
}

export const VIEW_TITLES: Record<string, string> = Object.fromEntries(routes.map((route) => [route.path, route.title]));

export function navigateTo(path: string): void {
  window.location.hash = path ? `#/${path}` : '#/app';
}

export function groupRoutes(filterFn?: (route: RouteDefinition) => boolean): Map<NavGroupTitle, RouteDefinition[]> {
  const groups = new Map<NavGroupTitle, RouteDefinition[]>();
  for (const route of routes) {
    if (!isRuntimeVisible(route)) continue;
    if (filterFn && !filterFn(route)) continue;
    const rows = groups.get(route.navGroup) ?? [];
    rows.push(route);
    groups.set(route.navGroup, rows);
  }
  return groups;
}

export function visibleRoutes(_operatorMode: boolean): RouteDefinition[] {
  return routes.filter(isRuntimeVisible);
}
