import { Suspense, useEffect, useMemo, useRef } from 'react';
import { HashRouter, Link, matchPath, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { AlertTriangle, ChevronDown, Layers3, Loader2, Moon, Sun } from 'lucide-react';
import type { ModelData } from './lib/data-parser';
import type { GovernedRunSummary } from './lib/governed-run';
import { selectRunFromQuery } from './lib/governed-run';
import type { RunWorkspaceContext } from './lib/run-workspace';
import { isProModelRun } from './lib/model-access';
import { ErrorBoundary } from './components/ErrorBoundary';
import { MobileNavigation } from './components/MobileNavigation';
import { ProModelGate } from './components/ProModelGate';
import { ResearchContextBar } from './components/ResearchContextBar';
import { Sidebar } from './components/Sidebar';
import { Button } from './components/ui/button';
import { Skeleton } from './components/ui/skeleton';
import { useAlphaMembership } from './hooks/useAlphaMembership';
import { useAppBootstrap } from './hooks/useAppBootstrap';
import { LandingPage } from './pages/LandingPage';
import { routes } from './routes';
import { useGlobalStore } from './store/globalStore';

const RUN_DETAIL_PATHS = new Set(['backtests', 'review', 'compare', 'decisions', 'factors', 'reports']);

function PageLoader() {
  return <div className="flex min-h-64 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary/60" /></div>;
}

function NotFound() {
  return (
    <div className="research-empty-state">
      <p className="text-6xl font-black text-muted-foreground/20">404</p>
      <h1 className="mt-3 text-xl font-semibold">Strategy view not found</h1>
      <p className="mt-2 text-sm text-muted-foreground">This route is not part of the current Alpha Engine strategy console.</p>
      <Button asChild variant="outline" className="mt-6"><Link to="/app">Open overview</Link></Button>
    </div>
  );
}

interface LayoutProps {
  models: ModelData[];
  selectedModelId: string;
  runs: GovernedRunSummary[];
  activeRunKey: string;
  selectRun: (run: GovernedRunSummary) => void;
  runLoadErrors: string[];
  loading: boolean;
  loadError: string | null;
}

function Layout(props: LayoutProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const mainRef = useRef<HTMLElement>(null);
  const membership = useAlphaMembership();
  const { theme, setTheme } = useGlobalStore();
  const declaredRoute = routes.find((route) => matchPath({ path: `/${route.path}`, end: true }, location.pathname));
  const viewTitle = declaredRoute?.title ?? 'Unavailable route';
  const activeRun = useMemo(
    () => props.runs.find((run) => run.key === props.activeRunKey) ?? props.runs[0] ?? null,
    [props.activeRunKey, props.runs],
  );
  const protectedRun = useMemo(() => {
    if (declaredRoute?.path === 'strategies/:strategyId') {
      const match = matchPath({ path: '/strategies/:strategyId', end: true }, location.pathname);
      const strategyId = match?.params.strategyId;
      return props.runs.find((run) => run.channel === 'formal' && run.modelVersionId === strategyId) ?? null;
    }
    if (declaredRoute && RUN_DETAIL_PATHS.has(declaredRoute.path)) {
      return selectRunFromQuery(props.runs, location.search) ?? activeRun;
    }
    return null;
  }, [activeRun, declaredRoute, location.pathname, location.search, props.runs]);
  const proRoute = isProModelRun(protectedRun);
  const proLocked = proRoute && !membership.isPro;
  const showRunPicker = Boolean(
    declaredRoute
    && ['backtests', 'review', 'compare', 'decisions'].includes(declaredRoute.path)
    && activeRun,
  );

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  useEffect(() => {
    document.title = `${viewTitle} — Alpha Engine`;
    const description = document.querySelector('meta[name="description"]');
    description?.setAttribute('content', 'Monitor governed systematic strategies, inspect target allocations, and drill into formal performance, risk, holdings and evidence.');
  }, [viewTitle]);

  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0, left: 0 });
  }, [location.pathname]);

  useEffect(() => {
    if (!props.runs.length || !location.search) return;
    const linked = selectRunFromQuery(props.runs, location.search);
    if (linked && linked.key !== props.activeRunKey) props.selectRun(linked);
  }, [location.search, props.activeRunKey, props.runs, props.selectRun]);

  const outletContext: RunWorkspaceContext = {
    models: props.models,
    selectedModelId: props.selectedModelId,
    runs: props.runs,
    activeRunKey: props.activeRunKey,
    activeRun,
    runLoadErrors: props.runLoadErrors,
    selectRun: props.selectRun,
  };

  return (
    <div className="research-app-shell">
      <Sidebar activeRun={activeRun} />
      <div className="research-workspace">
        <header className="research-topbar">
          <div className="min-w-0">
            <p className="research-topbar-eyebrow">Alpha Engine / Strategy Console</p>
            <div className="flex min-w-0 items-center gap-3">
              <h1 className="truncate">{viewTitle}</h1>
              {showRunPicker && activeRun && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigate('/runs')}
                  className="hidden h-7 max-w-[420px] gap-1.5 border-primary/20 bg-background/70 text-xs sm:inline-flex"
                >
                  <Layers3 className="h-3.5 w-3.5 shrink-0 text-primary" />
                  <span className="truncate font-medium">{activeRun.title}</span>
                  <span className="rounded bg-muted px-1 py-0.5 text-[9px] font-bold uppercase">{activeRun.channel}</span>
                  <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                </Button>
              )}
            </div>
          </div>

          <div className="research-topbar-actions">
            <MobileNavigation />
            <div className="alpha-account-slot" data-account-slot aria-label="AlphaEngine account" />
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              aria-label={theme === 'dark' ? 'Use light theme' : 'Use dark theme'}
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            >
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
          </div>
        </header>

        <ResearchContextBar />

        <main ref={mainRef} className="research-main">
          {props.loading || (proRoute && membership.loading) ? (
            <div className="space-y-6">
              <div className="grid gap-4 md:grid-cols-3">
                {Array.from({ length: 3 }).map((_, index) => <Skeleton key={index} className="h-28 rounded-xl" />)}
              </div>
              <Skeleton className="h-[360px] rounded-xl" />
            </div>
          ) : props.loadError ? (
            <div className="research-empty-state">
              <AlertTriangle className="mx-auto h-8 w-8 text-amber-500" />
              <h2 className="mt-4 text-lg font-semibold">Strategy evidence unavailable</h2>
              <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">{props.loadError}</p>
              <Button asChild variant="outline" className="mt-5"><Link to="/library">Open bundle library</Link></Button>
            </div>
          ) : proLocked && protectedRun ? (
            <ProModelGate run={protectedRun} openAccount={membership.openAccount} />
          ) : (
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <Outlet context={outletContext} />
              </Suspense>
            </ErrorBoundary>
          )}
        </main>
      </div>
    </div>
  );
}

function StrategyConsoleApp() {
  const workspace = useAppBootstrap();

  return (
    <Routes>
      <Route element={
        <Layout
          models={workspace.models}
          selectedModelId={workspace.selectedModelId}
          runs={workspace.runs}
          activeRunKey={workspace.activeRunKey}
          selectRun={workspace.selectRun}
          runLoadErrors={workspace.runLoadErrors}
          loading={workspace.loading}
          loadError={workspace.loadError}
        />
      }>
        {routes.map((route) => {
          const Component = route.component;
          return <Route key={route.path} path={route.path} element={<Component models={workspace.models} />} />;
        })}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

function AlphaEngineApp() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/*" element={<StrategyConsoleApp />} />
      </Routes>
    </HashRouter>
  );
}

export default AlphaEngineApp;
