import { Suspense, useEffect, useMemo, useRef } from 'react';
import { HashRouter, Link, matchPath, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { AlertTriangle, Loader2, Moon, Sun } from 'lucide-react';
import { ErrorBoundary } from './components/ErrorBoundary';
import { MobileNavigation } from './components/MobileNavigation';
import { MobileTabBar } from './components/MobileTabBar';
import { ResearchContextBar } from './components/ResearchContextBar';
import { Sidebar } from './components/Sidebar';
import { Button } from './components/ui/button';
import { Skeleton } from './components/ui/skeleton';
import { AccessControlProvider } from './hooks/useAccessControl';
import { useAppBootstrap } from './hooks/useAppBootstrap';
import type { RunWorkspaceContext } from './lib/run-workspace';
import { routes } from './routes';
import { useGlobalStore } from './store/globalStore';

function Layout(props: ReturnType<typeof useAppBootstrap>) {
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const { theme, setTheme } = useGlobalStore();
  const declared = routes.find(route => matchPath({ path: '/' + route.path, end: true }, location.pathname));
  const title = declared?.title ?? 'Unavailable route';
  const activeRun = useMemo(() => props.runs.find(run => run.key === props.activeRunKey) ?? props.runs[0] ?? null,
    [props.activeRunKey, props.runs]);
  useEffect(() => { document.documentElement.classList.toggle('dark', theme === 'dark'); }, [theme]);
  useEffect(() => { document.title = title + ' — Alpha Engine'; }, [title]);
  useEffect(() => { mainRef.current?.scrollTo({ top: 0, left: 0 }); }, [location.pathname]);
  const context: RunWorkspaceContext = {
    runs: props.runs, activeRunKey: props.activeRunKey, activeRun,
    runLoadErrors: props.runLoadErrors, selectRun: props.selectRun,
  };
  return <div className="research-app-shell">
    <Sidebar activeRun={activeRun} />
    <div className="research-workspace">
      <header className="research-topbar">
        <div className="min-w-0"><p className="research-topbar-eyebrow">Alpha Engine / Research only</p><h1 className="truncate">{title}</h1></div>
        <div className="research-topbar-actions">
          <MobileNavigation />
          <div className="alpha-account-slot" data-account-slot aria-label="AlphaEngine account" />
          <Button variant="ghost" size="icon" className="h-8 w-8"
            aria-label={theme === 'dark' ? 'Use light theme' : 'Use dark theme'}
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
      </header>
      <ResearchContextBar run={activeRun} fleet={location.pathname === '/app' ? props.runs : undefined} />
      <main ref={mainRef} className="research-main">
        {props.loading ? <div className="space-y-6"><Skeleton className="h-28 rounded-xl" /><Skeleton className="h-96 rounded-xl" /></div>
          : props.loadError ? <div className="research-empty-state">
            <AlertTriangle className="mx-auto h-8 w-8 text-amber-500" />
            <h2 className="mt-4 text-lg font-semibold">Strategy evidence unavailable</h2>
            <p className="mt-2 text-sm text-muted-foreground">{props.loadError}</p>
            <Button variant="outline" className="mt-5" onClick={() => void props.reload()}>Retry evidence reading</Button>
          </div>
          : <ErrorBoundary><Suspense fallback={<div className="flex min-h-64 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin" /></div>}>
            <Outlet context={context} />
          </Suspense></ErrorBoundary>}
      </main>
      <MobileTabBar />
    </div>
  </div>;
}
function Console() {
  const workspace = useAppBootstrap();
  return <Routes>
    <Route path="/" element={<Navigate to="/app" replace />} />
    <Route element={<Layout {...workspace} />}>
      {routes.map(route => { const Component = route.component; return <Route key={route.path} path={route.path} element={<Component />} />; })}
      <Route path="*" element={<div className="research-empty-state"><h1>View unavailable</h1><p>This view is outside the daily research console.</p><Link to="/app">Open overview</Link></div>} />
    </Route>
  </Routes>;
}
export default function App() {
  return <AccessControlProvider><HashRouter><Console /></HashRouter></AccessControlProvider>;
}
