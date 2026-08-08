import {
  BarChart3,
  BookOpen,
  CandlestickChart,
  Database,
  FileCheck2,
  FolderArchive,
  GitCompareArrows,
  LayoutDashboard,
  ListTree,
  ScrollText,
  Settings2,
  ShieldQuestion,
  Sparkles,
} from 'lucide-react';
import { lazy, type ComponentType } from 'react';

export type ReleaseLevel = 'release' | 'experimental' | 'internal';
export type NavGroupTitle = 'Monitor' | 'Research' | 'System';

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

const OverviewPage = lazy(() => import('./pages/StrategyOverviewPage').then((m) => ({ default: m.StrategyOverviewPage })));
const StrategiesPage = lazy(() => import('./pages/StrategiesPage').then((m) => ({ default: m.StrategiesPage })));
const StrategyDetailPage = lazy(() => import('./pages/StrategyDetailPage').then((m) => ({ default: m.StrategyDetailPage })));
const SecurityExplorerPage = lazy(() => import('./pages/SecurityExplorerPage').then((m) => ({ default: m.SecurityExplorerPage })));
const ResearchHubPage = lazy(() => import('./pages/ResearchHubPage').then((m) => ({ default: m.ResearchHubPage })));
const SystemHubPage = lazy(() => import('./pages/SystemHubPage').then((m) => ({ default: m.SystemHubPage })));
const LibraryPage = lazy(() => import('./pages/LibraryPage').then((m) => ({ default: m.LibraryPage })));
const RunsPage = lazy(() => import('./pages/RunsPage').then((m) => ({ default: m.RunsPage })));
const FormalBacktestsPage = lazy(() => import('./pages/FormalBacktestsPage').then((m) => ({ default: m.FormalBacktestsPage })));
const RunReviewPage = lazy(() => import('./pages/RunReviewPage').then((m) => ({ default: m.RunReviewPage })));
const EvidenceDataPage = lazy(() => import('./pages/EvidenceDataPage').then((m) => ({ default: m.EvidenceDataPage })));
const EvidenceFactorsPage = lazy(() => import('./pages/EvidenceFactorsPage').then((m) => ({ default: m.EvidenceFactorsPage })));
const EvidenceReportsPage = lazy(() => import('./pages/EvidenceReportsPage').then((m) => ({ default: m.EvidenceReportsPage })));
const ComparePage = lazy(() => import('./pages/ComparePage').then((m) => ({ default: m.ComparePage })));
const DecisionsPage = lazy(() => import('./pages/DecisionsPage').then((m) => ({ default: m.DecisionsPage })));
const MethodologyPage = lazy(() => import('./pages/MethodologyPage').then((m) => ({ default: m.MethodologyPage })));

/** Product navigation is strategy-centric; evidence views remain drill-down routes. */
export const routes: RouteDefinition[] = [
  { path: 'app', title: 'Strategy Overview', label: 'Overview', releaseLevel: 'release', navGroup: 'Monitor', icon: LayoutDashboard, component: OverviewPage },
  { path: 'strategies', title: 'Formal Strategies', label: 'Strategies', releaseLevel: 'release', navGroup: 'Monitor', icon: Sparkles, component: StrategiesPage },
  { path: 'securities', title: 'Security Explorer', label: 'Securities', releaseLevel: 'release', navGroup: 'Monitor', icon: CandlestickChart, component: SecurityExplorerPage },
  { path: 'strategies/:strategyId', title: 'Strategy', label: 'Strategy', releaseLevel: 'release', navGroup: 'Monitor', icon: Sparkles, component: StrategyDetailPage, navVisible: false },
  { path: 'research', title: 'Strategy Research', label: 'Research', releaseLevel: 'release', navGroup: 'Research', icon: ListTree, component: ResearchHubPage },
  { path: 'system', title: 'System Trust', label: 'System', releaseLevel: 'release', navGroup: 'System', icon: Settings2, component: SystemHubPage },

  { path: 'runs', title: 'Governed Model Runs', label: 'Runs', releaseLevel: 'release', navGroup: 'Research', icon: ListTree, component: RunsPage, navVisible: false },
  { path: 'backtests', title: 'Formal Backtests', label: 'Backtests', releaseLevel: 'release', navGroup: 'Research', icon: BarChart3, component: FormalBacktestsPage, navVisible: false },
  { path: 'review', title: 'Run Review', label: 'Review', releaseLevel: 'release', navGroup: 'Research', icon: FileCheck2, component: RunReviewPage, navVisible: false },
  { path: 'compare', title: 'Compatible Run Comparison', label: 'Compare', releaseLevel: 'release', navGroup: 'Research', icon: GitCompareArrows, component: ComparePage, navVisible: false },
  { path: 'decisions', title: 'Research Decisions', label: 'Decisions', releaseLevel: 'release', navGroup: 'Research', icon: ShieldQuestion, component: DecisionsPage, navVisible: false },
  { path: 'factors', title: 'Factor Evidence', label: 'Factors', releaseLevel: 'release', navGroup: 'Research', icon: BarChart3, component: EvidenceFactorsPage, navVisible: false },
  { path: 'reports', title: 'Reports & Notebooks', label: 'Reports', releaseLevel: 'release', navGroup: 'Research', icon: ScrollText, component: EvidenceReportsPage, navVisible: false },

  { path: 'data', title: 'Data Lineage', label: 'Data', releaseLevel: 'release', navGroup: 'System', icon: Database, component: EvidenceDataPage, navVisible: false },
  { path: 'library', title: 'Local Bundle Library', label: 'Library', releaseLevel: 'release', navGroup: 'System', icon: FolderArchive, component: LibraryPage, navVisible: false },
  { path: 'methodology', title: 'Methodology & Boundaries', label: 'Methodology', releaseLevel: 'release', navGroup: 'System', icon: BookOpen, component: MethodologyPage, navVisible: false },
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
