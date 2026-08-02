import { Suspense, useEffect, useLayoutEffect, useState } from 'react';
import { HashRouter, Link, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { ChevronDown, Database, Loader2, Moon, Sun, User } from 'lucide-react';
import type { JobEnvelope } from './api/jobsApi';
import type { ModelData } from './lib/data-parser';
import { AuthGuard } from './components/AuthGuard';
import { ConsoleModal } from './components/ConsoleModal';
import { ErrorBoundary } from './components/ErrorBoundary';
import { GlobalStatusBar } from './components/GlobalStatusBar';
import { ModelSelector } from './components/ModelSelector';
import { ResearchContextBar } from './components/ResearchContextBar';
import { Sidebar } from './components/Sidebar';
import { Button } from './components/ui/button';
import { Skeleton } from './components/ui/skeleton';
import { useAppBootstrap } from './hooks/useAppBootstrap';
import { setAuthHeaderProvider } from './lib/api';
import { useAuth } from './lib/auth';
import { runtimeCapabilities } from './lib/runtime-capabilities';
import { isRuntimeVisible, routes, VIEW_TITLES } from './routes';
import { useGlobalStore } from './store/globalStore';

function PageLoader() {
  return <div className="flex min-h-64 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary/60" /></div>;
}

function NotFound() {
  return (
    <div className="research-empty-state">
      <p className="text-6xl font-black text-muted-foreground/20">404</p>
      <h1 className="mt-3 text-xl font-semibold">Evidence view not found</h1>
      <p className="mt-2 text-sm text-muted-foreground">This route is not available in the active runtime. Return to the research overview and choose a declared artifact.</p>
      <Button asChild variant="outline" className="mt-6"><Link to="/">Back to overview</Link></Button>
    </div>
  );
}

interface LayoutProps {
  models: ModelData[];
  selectedModelId: string;
  setSelectedModelId: (id: string) => void;
  selectorOpen: boolean;
  setSelectorOpen: (open: boolean) => void;
  consoleOpen: boolean;
  setConsoleOpen: (open: boolean) => void;
  handleDeleteModel: (id: string) => Promise<void>;
  loading: boolean;
  refreshModels: (opts?: { selectLatest?: boolean }) => Promise<ModelData[] | null>;
  refreshDataStatus: () => Promise<void>;
  submitAndPoll: (submitFn: () => Promise<JobEnvelope>, onComplete?: (status: string) => void) => Promise<JobEnvelope>;
}

function Layout(props: LayoutProps) {
  const location = useLocation();
  const {
    latestCalendarDay, qualityStatus, qualityWarnings, activeJobsCount, dataGeneratedAt,
    apiError, theme, setTheme, username,
  } = useGlobalStore();
  const { logout } = useAuth();
  const currentPath = location.pathname.replace(/^\//, '');
  const viewTitle = VIEW_TITLES[currentPath] ?? currentPath.replace('-', ' ');
  const selectedModel = props.models.find((model) => model.id === props.selectedModelId);
  const showModelPicker = ['dashboard', 'models', 'compare'].includes(currentPath) && selectedModel;

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  return (
    <div className="research-app-shell">
      <Sidebar />
      <div className="research-workspace">
        {runtimeCapabilities.backendApi && (
          <GlobalStatusBar
            latestCalendarDay={latestCalendarDay}
            qualityStatus={qualityStatus}
            warnings={qualityWarnings}
            activeJobsCount={activeJobsCount}
            dataGeneratedAt={dataGeneratedAt}
            apiError={apiError}
            onOpenConsole={() => props.setConsoleOpen(true)}
          />
        )}

        <header className="research-topbar">
          <div className="min-w-0">
            <p className="research-topbar-eyebrow">Alpha Engine / Evidence workspace</p>
            <div className="flex min-w-0 items-center gap-3">
              <h1 className="truncate">{viewTitle}</h1>
              {showModelPicker && (
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
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              aria-label={theme === 'dark' ? 'Use light theme' : 'Use dark theme'}
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            >
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            {runtimeCapabilities.requiresAuthentication && (
              <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" onClick={() => logout()}>
                <User className="h-3.5 w-3.5" /><span>{username}</span>
              </Button>
            )}
          </div>
        </header>

        <ResearchContextBar />

        <main className="research-main">
          {props.loading ? (
            <div className="space-y-6">
              <div className="grid gap-4 md:grid-cols-3">{Array.from({ length: 3 }).map((_, index) => <Skeleton key={index} className="h-28 rounded-xl" />)}</div>
              <Skeleton className="h-[360px] rounded-xl" />
            </div>
          ) : (
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <Outlet context={{
                  models: props.models,
                  selectedModelId: props.selectedModelId,
                  refreshModels: props.refreshModels,
                  refreshDataStatus: props.refreshDataStatus,
                  submitAndPoll: props.submitAndPoll,
                }} />
              </Suspense>
            </ErrorBoundary>
          )}
        </main>

        <ModelSelector
          models={props.models}
          selectedModelId={props.selectedModelId}
          onSelect={props.setSelectedModelId}
          onDelete={props.handleDeleteModel}
          canDelete={runtimeCapabilities.mutations}
          open={props.selectorOpen}
          onOpenChange={props.setSelectorOpen}
        />

        {runtimeCapabilities.backendApi && (
          <ConsoleModal isOpen={props.consoleOpen} onClose={() => props.setConsoleOpen(false)} warnings={qualityWarnings} />
        )}
      </div>
    </div>
  );
}

function App() {
  const { authHeader } = useAuth();
  useLayoutEffect(() => {
    setAuthHeaderProvider(authHeader);
    return () => setAuthHeaderProvider(null);
  }, [authHeader]);
  return <AuthGuard><AuthenticatedApp /></AuthGuard>;
}

function AuthenticatedApp() {
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const {
    loading, models, selectedModelId, setSelectedModelId, deleteModel,
    fetchModels, loadDataStatus, jobs,
  } = useAppBootstrap();

  const handleDeleteModel = async (id: string) => {
    if (runtimeCapabilities.mutations) await deleteModel(id);
  };

  return (
    <HashRouter>
      <Routes>
        <Route element={
          <Layout
            models={models}
            selectedModelId={selectedModelId}
            setSelectedModelId={setSelectedModelId}
            selectorOpen={selectorOpen}
            setSelectorOpen={setSelectorOpen}
            consoleOpen={consoleOpen}
            setConsoleOpen={setConsoleOpen}
            handleDeleteModel={handleDeleteModel}
            loading={loading}
            refreshModels={fetchModels}
            refreshDataStatus={loadDataStatus}
            submitAndPoll={jobs.submitAndPoll}
          />
        }>
          {routes.filter(isRuntimeVisible).map((route) => {
            const Component = route.component;
            return <Route key={route.path} path={route.path} element={<Component models={models} />} />;
          })}
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}

export default App;
