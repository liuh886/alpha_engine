import { Suspense, useEffect, useState } from 'react';
import { HashRouter, Link, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { AlertTriangle, ChevronDown, Database, Loader2, Moon, Sun } from 'lucide-react';
import type { ModelData } from './lib/data-parser';
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
        This route is not part of the Research Artifact Studio. Return to the overview and choose a declared artifact view.
      </p>
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
  loading: boolean;
  loadError: string | null;
}

function Layout(props: LayoutProps) {
  const location = useLocation();
  const { theme, setTheme } = useGlobalStore();
  const currentPath = location.pathname.replace(/^\//, '');
  const declaredRoute = routes.find((route) => route.path === currentPath);
  const viewTitle = declaredRoute?.title ?? 'Unavailable route';
  const selectedModel = props.models.find((model) => model.id === props.selectedModelId);
  const showModelPicker = Boolean(
    declaredRoute
    && ['dashboard', 'models', 'compare'].includes(currentPath)
    && selectedModel,
  );

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  return (
    <div className="research-app-shell">
      <Sidebar />
      <div className="research-workspace">
        <header className="research-topbar">
          <div className="min-w-0">
            <p className="research-topbar-eyebrow">Alpha Engine / Research Artifact Studio</p>
            <div className="flex min-w-0 items-center gap-3">
              <h1 className="truncate">{viewTitle}</h1>
              {showModelPicker && selectedModel && (
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
                <Outlet context={{ models: props.models, selectedModelId: props.selectedModelId }} />
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
  const { loading, loadError, models, selectedModelId, setSelectedModelId } = useAppBootstrap();

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
            loading={loading}
            loadError={loadError}
          />
        }>
          {routes.map((route) => {
            const Component = route.component;
            return <Route key={route.path} path={route.path} element={<Component models={models} />} />;
          })}
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}

export default ArtifactStudioApp;
