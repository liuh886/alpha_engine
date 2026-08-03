import { Suspense, useEffect, useMemo, useState } from 'react';
import { HashRouter, Link, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { AlertTriangle, ChevronDown, Database, Layers3, Loader2, Moon, Sun } from 'lucide-react';
import type { ModelData } from './lib/data-parser';
import type { GovernedRunSummary } from './lib/governed-run';
import { selectRunFromQuery } from './lib/governed-run';
import type { RunWorkspaceContext } from './lib/run-workspace';
import { ErrorBoundary } from './components/ErrorBoundary';
import { MobileNavigation } from './components/MobileNavigation';
import { ModelSelector } from './components/ModelSelector';
import { ResearchContextBar } from './components/ResearchContextBar';
import { Sidebar } from './components/Sidebar';
import { Button } from './components/ui/button';
import { Skeleton } from './components/ui/skeleton';
import { useAppBootstrap } from './hooks/useAppBootstrap';
import { routes } from './routes';
import { useGlobalStore } from './store/globalStore';

function PageLoader() {
  return <div className="flex min-h-64 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary/60" /></div>;
}

function NotFound() {
  return (
    <div className="research-empty-state">
      <p className="text-6xl font-black text-muted-foreground/20">404</p>
      <h1 className="mt-3 text-xl font-semibold">Evidence view not found</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        This route is not part of the governed research workspace. Return to Runs and choose a declared artifact.
      </p>
      <Button asChild variant="outline" className="mt-6"><Link to="/runs">Open Runs</Link></Button>
    </div>
  );
}

interface LayoutProps {
  models: ModelData[];
  selectedModelId: string;
  setSelectedModelId: (id: string) => void;
  runs: GovernedRunSummary[];
  activeRunKey: string;
  selectRun: (run: GovernedRunSummary) => void;
  runLoadErrors: string[];
  selectorOpen: boolean;
  setSelectorOpen: (open: boolean) => void;
  loading: boolean;
  loadError: string | null;
}

function Layout(props: LayoutProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, setTheme } = useGlobalStore();
  const currentPath = location.pathname.replace(/^\//, '');
  const declaredRoute = routes.find((route) => route.path === currentPath);
  const viewTitle = declaredRoute?.title ?? 'Unavailable route';
  const selectedModel = props.models.find((model) => model.id === props.selectedModelId);
  const activeRun = useMemo(
    () => props.runs.find((run) => run.key === props.activeRunKey) ?? props.runs[0] ?? null,
    [props.activeRunKey, props.runs],
  );
  const showLegacyModelPicker = Boolean(
    declaredRoute
    && ['dashboard', 'models'].includes(currentPath)
    && selectedModel,
  );
  const showRunPicker = Boolean(
    declaredRoute
    && ['review', 'compare', 'decisions'].includes(currentPath)
    && activeRun,
  );

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  useEffect(() => {
    if (!props.runs.length || !location.search) return;
    const linked = selectRunFromQuery(props.runs, location.search);
    if (linked && linked.key !== props.activeRunKey) props.selectRun(linked);
  }, [location.search, props]);

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
      <Sidebar />
      <div className="research-workspace">
        <header className="research-topbar">
          <div className="min-w-0">
            <p className="research-topbar-eyebrow">Alpha Engine / Governed Research Studio</p>
            <div className="flex min-w-0 items-center gap-3">
              <h1 className="truncate">{viewTitle}</h1>
              {showRunPicker && activeRun && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigate('/runs')}
                  className="h-7 max-w-[420px] gap-1.5 border-primary/20 bg-background/70 text-xs"
                >
                  <Layers3 className="h-3.5 w-3.5 shrink-0 text-primary" />
                  <span className="truncate font-medium">{activeRun.title}</span>
                  <span className="rounded bg-muted px-1 py-0.5 text-[9px] font-bold uppercase">{activeRun.channel}</span>
                  <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                </Button>
              )}
              {showLegacyModelPicker && selectedModel && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => props.setSelectorOpen(true)}
                  className="h-7 max-w-[320px] gap-1.5 border-primary/20 bg-background/70 text-xs"
                >
                  <Database className="h-3.5 w-3.5 shrink-0 text-primary" />
                  <span className="truncate font-medium">{selectedModel.name}</span>
                  <span className="rounded bg-muted px-1 py-0.5 text-[9px] font-bold uppercase">{selectedModel.market}</span>
                  <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                </Button>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <MobileNavigation />
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

        <main className="research-main">
          {props.loading ? (
            <div className="space-y-6">
              <div className="grid gap-4 md:grid-cols-3">
                {Array.from({ length: 3 }).map((_, index) => <Skeleton key={index} className="h-28 rounded-xl" />)}
              </div>
              <Skeleton className="h-[360px] rounded-xl" />
            </div>
          ) : props.loadError ? (
            <div className="research-empty-state">
              <AlertTriangle className="mx-auto h-8 w-8 text-amber-500" />
              <h2 className="mt-4 text-lg font-semibold">Research bundle unavailable</h2>
              <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">{props.loadError}</p>
              <Button asChild variant="outline" className="mt-5"><Link to="/library">Open bundle library</Link></Button>
            </div>
          ) : (
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <Outlet context={outletContext} />
              </Suspense>
            </ErrorBoundary>
          )}
        </main>

        <ModelSelector
          models={props.models}
          selectedModelId={props.selectedModelId}
          onSelect={props.setSelectedModelId}
          open={props.selectorOpen}
          onOpenChange={props.setSelectorOpen}
        />
      </div>
    </div>
  );
}

function ArtifactStudioApp() {
  const [selectorOpen, setSelectorOpen] = useState(false);
  const workspace = useAppBootstrap();

  return (
    <HashRouter>
      <Routes>
        <Route element={
          <Layout
            models={workspace.models}
            selectedModelId={workspace.selectedModelId}
            setSelectedModelId={workspace.setSelectedModelId}
            runs={workspace.runs}
            activeRunKey={workspace.activeRunKey}
            selectRun={workspace.selectRun}
            runLoadErrors={workspace.runLoadErrors}
            selectorOpen={selectorOpen}
            setSelectorOpen={setSelectorOpen}
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
    </HashRouter>
  );
}

export default ArtifactStudioApp;
