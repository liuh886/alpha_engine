import {
  Activity, BarChart3, BookOpen, Bot, ClipboardList, Cpu, Database, FileText,
  FlaskConical, FolderArchive, Layers, LayoutDashboard, ListChecks, PieChart,
  Radar, ScrollText, Settings, Swords, Terminal,
} from 'lucide-react';
import { lazy, type ComponentType } from 'react';
import { runtimeCapabilities } from './lib/runtime-capabilities';

export type ReleaseLevel = 'release' | 'experimental' | 'internal';
export type NavGroupTitle = 'Library' | 'Evidence' | 'Reference' | 'Developer';
export type RouteSurface = 'artifact' | 'connected' | 'both';

export interface RouteDefinition {
  path: string;
  title: string;
  releaseLevel: ReleaseLevel;
  navGroup: NavGroupTitle;
  surface: RouteSurface;
  icon: ComponentType<{ className?: string }>;
  label: string;
  component: ComponentType<any>;
}

const HomePage = lazy(() => import('./pages/ArtifactStudioHomePage').then((m) => ({ default: m.ArtifactStudioHomePage })));
const LibraryPage = lazy(() => import('./pages/LibraryPage').then((m) => ({ default: m.LibraryPage })));
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })));
const EvidenceModelsPage = lazy(() => import('./pages/EvidenceModelsPage').then((m) => ({ default: m.EvidenceModelsPage })));
const EvidenceDataPage = lazy(() => import('./pages/EvidenceDataPage').then((m) => ({ default: m.EvidenceDataPage })));
const EvidenceFactorsPage = lazy(() => import('./pages/EvidenceFactorsPage').then((m) => ({ default: m.EvidenceFactorsPage })));
const EvidenceExperimentsPage = lazy(() => import('./pages/EvidenceExperimentsPage').then((m) => ({ default: m.EvidenceExperimentsPage })));
const EvidenceReportsPage = lazy(() => import('./pages/EvidenceReportsPage').then((m) => ({ default: m.EvidenceReportsPage })));
const ComparePage = lazy(() => import('./pages/ComparePage').then((m) => ({ default: m.ComparePage })));
const MethodologyPage = lazy(() => import('./pages/MethodologyPage').then((m) => ({ default: m.MethodologyPage })));

const DecisionDeskPage = lazy(() => import('./pages/DecisionDeskPage').then((m) => ({ default: m.DecisionDeskPage })));
const StrategyPage = lazy(() => import('./pages/StrategyPage').then((m) => ({ default: m.StrategyPage })));
const ArenaPage = lazy(() => import('./pages/ArenaPage').then((m) => ({ default: m.ArenaPage })));
const RuntimeReportsPage = lazy(() => import('./pages/ReportsPage').then((m) => ({ default: m.ReportsPage })));
const RuntimeModelsPage = lazy(() => import('./pages/ModelsPage').then((m) => ({ default: m.ModelsPage })));
const RuntimeDataPage = lazy(() => import('./pages/DataPage').then((m) => ({ default: m.DataPage })));
const RuntimeFactorPage = lazy(() => import('./pages/FactorPage').then((m) => ({ default: m.FactorPage })));
const FactorRegistryPage = lazy(() => import('./pages/FactorRegistryPage').then((m) => ({ default: m.FactorRegistryPage })));
const RuntimeExperimentPage = lazy(() => import('./pages/ExperimentLogPage').then((m) => ({ default: m.ExperimentLogPage })));
const AttributionPage = lazy(() => import('./pages/AttributionPage').then((m) => ({ default: m.AttributionPage })));
const StockTerminal = lazy(() => import('./pages/StockTerminal').then((m) => ({ default: m.StockTerminal })));
const AgentControlCenter = lazy(() => import('./pages/AgentControlCenter').then((m) => ({ default: m.AgentControlCenter })));
const DocsPage = lazy(() => import('./pages/DocsPage').then((m) => ({ default: m.DocsPage })));
const BacktestPage = lazy(() => import('./pages/BacktestPage').then((m) => ({ default: m.BacktestPage })));
const SystemPage = lazy(() => import('./pages/SystemPage').then((m) => ({ default: m.SystemPage })));
const TopBottomPage = lazy(() => import('./components/TopBottomAnalysis').then((m) => ({ default: m.TopBottomAnalysis })));

export const routes: RouteDefinition[] = [
  { path: 'library', title: 'Research Library', label: 'Library', releaseLevel: 'release', navGroup: 'Library', surface: 'artifact', icon: FolderArchive, component: LibraryPage },
  { path: '', title: 'Evidence Overview', label: 'Overview', releaseLevel: 'release', navGroup: 'Library', surface: 'artifact', icon: LayoutDashboard, component: HomePage },

  { path: 'dashboard', title: 'Backtest Evidence', label: 'Backtests', releaseLevel: 'release', navGroup: 'Evidence', surface: 'artifact', icon: FlaskConical, component: DashboardPage },
  { path: 'models', title: 'Model Evidence', label: 'Models', releaseLevel: 'release', navGroup: 'Evidence', surface: 'artifact', icon: Cpu, component: EvidenceModelsPage },
  { path: 'compare', title: 'Evidence Comparison', label: 'Compare', releaseLevel: 'release', navGroup: 'Evidence', surface: 'artifact', icon: Layers, component: ComparePage },
  { path: 'data', title: 'Data Evidence', label: 'Data', releaseLevel: 'release', navGroup: 'Evidence', surface: 'artifact', icon: Database, component: EvidenceDataPage },
  { path: 'factors', title: 'Factor Evidence', label: 'Factors', releaseLevel: 'release', navGroup: 'Evidence', surface: 'artifact', icon: BarChart3, component: EvidenceFactorsPage },
  { path: 'experiments', title: 'Experiment Journal', label: 'Experiments', releaseLevel: 'release', navGroup: 'Evidence', surface: 'artifact', icon: ClipboardList, component: EvidenceExperimentsPage },
  { path: 'reports', title: 'Reports & Notebooks', label: 'Reports', releaseLevel: 'release', navGroup: 'Evidence', surface: 'artifact', icon: ScrollText, component: EvidenceReportsPage },

  { path: 'methodology', title: 'Research Methodology', label: 'Methodology', releaseLevel: 'release', navGroup: 'Reference', surface: 'artifact', icon: BookOpen, component: MethodologyPage },
  { path: 'docs', title: 'System Documentation', label: 'Documentation', releaseLevel: 'release', navGroup: 'Reference', surface: 'connected', icon: FileText, component: DocsPage },

  { path: 'decision-desk', title: 'Decision Desk', label: 'Decision Desk', releaseLevel: 'experimental', navGroup: 'Developer', surface: 'connected', icon: Radar, component: DecisionDeskPage },
  { path: 'terminal', title: 'Stock Terminal', label: 'Stock Terminal', releaseLevel: 'experimental', navGroup: 'Developer', surface: 'connected', icon: Terminal, component: StockTerminal },
  { path: 'runtime-models', title: 'Runtime Model Registry', label: 'Runtime Models', releaseLevel: 'internal', navGroup: 'Developer', surface: 'connected', icon: Cpu, component: RuntimeModelsPage },
  { path: 'runtime-data', title: 'Runtime Data Manager', label: 'Runtime Data', releaseLevel: 'internal', navGroup: 'Developer', surface: 'connected', icon: Database, component: RuntimeDataPage },
  { path: 'runtime-factors', title: 'Runtime Factor Analysis', label: 'Runtime Factors', releaseLevel: 'internal', navGroup: 'Developer', surface: 'connected', icon: BarChart3, component: RuntimeFactorPage },
  { path: 'runtime-experiments', title: 'Runtime Experiment Log', label: 'Runtime Experiments', releaseLevel: 'internal', navGroup: 'Developer', surface: 'connected', icon: ClipboardList, component: RuntimeExperimentPage },
  { path: 'runtime-reports', title: 'Runtime Reports', label: 'Runtime Reports', releaseLevel: 'internal', navGroup: 'Developer', surface: 'connected', icon: ScrollText, component: RuntimeReportsPage },
  { path: 'factor-registry', title: 'Factor Registry', label: 'Factor Registry', releaseLevel: 'experimental', navGroup: 'Developer', surface: 'connected', icon: ListChecks, component: FactorRegistryPage },
  { path: 'strategy', title: 'Strategy Spec', label: 'Strategy Spec', releaseLevel: 'experimental', navGroup: 'Developer', surface: 'connected', icon: Settings, component: StrategyPage },
  { path: 'arena', title: 'Arena', label: 'Arena', releaseLevel: 'experimental', navGroup: 'Developer', surface: 'connected', icon: Swords, component: ArenaPage },
  { path: 'backtest', title: 'Backtest Workbench', label: 'Run Research', releaseLevel: 'internal', navGroup: 'Developer', surface: 'connected', icon: FlaskConical, component: BacktestPage },
  { path: 'top-bottom', title: 'Top/Bottom Analysis', label: 'Top/Bottom', releaseLevel: 'experimental', navGroup: 'Developer', surface: 'connected', icon: BarChart3, component: TopBottomPage },
  { path: 'attribution', title: 'Factor Attribution', label: 'Attribution', releaseLevel: 'experimental', navGroup: 'Developer', surface: 'connected', icon: PieChart, component: AttributionPage },
  { path: 'system', title: 'System Monitor', label: 'System', releaseLevel: 'internal', navGroup: 'Developer', surface: 'connected', icon: Activity, component: SystemPage },
  { path: 'agent', title: 'Agent Center', label: 'Agent Center', releaseLevel: 'internal', navGroup: 'Developer', surface: 'connected', icon: Bot, component: AgentControlCenter },
];

export function isRuntimeVisible(route: RouteDefinition): boolean {
  if (runtimeCapabilities.backendApi) return true;
  return route.surface === 'artifact' || route.surface === 'both';
}

export const VIEW_TITLES: Record<string, string> = Object.fromEntries(routes.map((route) => [route.path, route.title]));

export function navigateTo(path: string): void {
  window.location.hash = path ? `#/${path}` : '#/';
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

export function visibleRoutes(operatorMode: boolean): RouteDefinition[] {
  return routes.filter((route) => {
    if (!isRuntimeVisible(route)) return false;
    if (route.releaseLevel === 'internal') return operatorMode;
    return true;
  });
}
