import { useState, useEffect, useLayoutEffect, lazy, Suspense } from 'react';
import { HashRouter, Routes, Route, useNavigate, useLocation, Outlet, Link } from 'react-router-dom';
import { parseQlibData, ModelData } from './lib/data-parser';
import { Dashboard } from './components/Dashboard';
import { ModelSelector } from './components/ModelSelector';
import { GlobalStatusBar } from './components/GlobalStatusBar';
import { Sidebar } from './components/Sidebar';
import { ConsoleModal } from './components/ConsoleModal';
import { ErrorBoundary } from './components/ErrorBoundary';
import { Skeleton } from './components/ui/skeleton';
import { Play, Loader2, Bell, User, Sun, Moon, ChevronDown, Database } from 'lucide-react';
import { Button } from "@/components/ui/button";
import { useGlobalStore } from './store/globalStore';
import { artifactUrl } from './lib/artifacts';
import { apiFetch, setAuthHeaderProvider } from './lib/api';
import { useAuth } from './lib/auth';
import { AuthGuard } from './components/AuthGuard';
import { VIEW_TITLES } from './routes';

// Lazy-loaded pages (code splitting)
const StrategyPage = lazy(() => import('./pages/StrategyPage').then(m => ({ default: m.StrategyPage })));
const ComparePage = lazy(() => import('./pages/ComparePage').then(m => ({ default: m.ComparePage })));
const ArenaPage = lazy(() => import('./pages/ArenaPage').then(m => ({ default: m.ArenaPage })));
const ReportsPage = lazy(() => import('./pages/ReportsPage').then(m => ({ default: m.ReportsPage })));
const ModelsPage = lazy(() => import('./pages/ModelsPage').then(m => ({ default: m.ModelsPage })));
const DataPage = lazy(() => import('./pages/DataPage').then(m => ({ default: m.DataPage })));
const FactorPage = lazy(() => import('./pages/FactorPage').then(m => ({ default: m.FactorPage })));
const FactorRegistryPage = lazy(() => import('./pages/FactorRegistryPage').then(m => ({ default: m.FactorRegistryPage })));
const ExperimentLogPage = lazy(() => import('./pages/ExperimentLogPage').then(m => ({ default: m.ExperimentLogPage })));
const AttributionPage = lazy(() => import('./pages/AttributionPage').then(m => ({ default: m.AttributionPage })));
const StockTerminal = lazy(() => import('./pages/StockTerminal').then(m => ({ default: m.StockTerminal })));
const AgentControlCenter = lazy(() => import('./pages/AgentControlCenter').then(m => ({ default: m.AgentControlCenter })));
const DocsPage = lazy(() => import('./pages/DocsPage').then(m => ({ default: m.DocsPage })));
const BacktestPage = lazy(() => import('./pages/BacktestPage').then(m => ({ default: m.BacktestPage })));
const MethodologyPage = lazy(() => import('./pages/MethodologyPage').then(m => ({ default: m.MethodologyPage })));
const SystemPage = lazy(() => import('./pages/SystemPage').then(m => ({ default: m.SystemPage })));

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-full p-8">
      <Loader2 className="h-6 w-6 animate-spin text-primary opacity-50" />
    </div>
  );
}

function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center py-32 text-center">
      <p className="text-6xl font-black text-muted-foreground/30 mb-4">404</p>
      <p className="text-muted-foreground font-medium mb-6">Page not found.</p>
      <Button asChild variant="outline" className="rounded-full px-8">
        <Link to="/">Back to Dashboard</Link>
      </Button>
    </div>
  );
}

function Layout({ models, selectedModelId, setSelectedModelId, selectorOpen, setSelectorOpen, consoleOpen, setConsoleOpen, startBacktestForSelectedMarket, backtestRunning, handleDeleteModel, loading }: {
  models: ModelData[];
  selectedModelId: string;
  setSelectedModelId: (id: string) => void;
  selectorOpen: boolean;
  setSelectorOpen: (open: boolean) => void;
  consoleOpen: boolean;
  setConsoleOpen: (open: boolean) => void;
  startBacktestForSelectedMarket: () => Promise<void>;
  backtestRunning: boolean;
  handleDeleteModel: (id: string) => Promise<void>;
  loading: boolean;
}) {
  const location = useLocation();
  const { latestCalendarDay, qualityStatus, qualityWarnings, activeJobsCount, dataGeneratedAt, apiError, theme, setTheme, username } = useGlobalStore();
  const { logout } = useAuth();

  const currentPath = location.pathname.replace(/^\//, '');
  const viewTitle = VIEW_TITLES[currentPath] ?? currentPath.replace('-', ' ');
  const selectedModel = models.find(m => m.id === selectedModelId);

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <GlobalStatusBar
          latestCalendarDay={latestCalendarDay}
          qualityStatus={qualityStatus}
          warnings={qualityWarnings}
          activeJobsCount={activeJobsCount}
          dataGeneratedAt={dataGeneratedAt}
          apiError={apiError}
          onOpenConsole={() => setConsoleOpen(true)}
        />

        <header className="h-11 border-b bg-card sticky top-0 z-40 px-5 flex items-center justify-between">
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <h2 className="font-semibold">{viewTitle}</h2>
            {(currentPath === 'dashboard' || currentPath === '') && selectedModel && (
              <>
                <div className="h-3.5 w-px bg-border" />
                <Button variant="outline" size="sm" onClick={() => setSelectorOpen(true)} className="text-xs font-mono h-7 gap-1.5 px-2.5 border-primary/20 hover:border-primary/40 hover:bg-primary/5">
                  <Database className="h-3 w-3 text-primary" />
                  <span className="font-bold">{selectedModel.name}</span>
                  {selectedModel.market && (
                    <span className="text-[9px] uppercase font-black tracking-widest text-muted-foreground bg-muted px-1 py-0.5 rounded">
                      {String(selectedModel.market)}
                    </span>
                  )}
                  <ChevronDown className="h-3 w-3 text-muted-foreground" />
                </Button>
              </>
            )}
          </div>

          <div className="flex items-center gap-2">
            {(currentPath === 'dashboard' || currentPath === '') && (
              <Button size="sm" variant="default" onClick={startBacktestForSelectedMarket} disabled={backtestRunning} className="h-7 gap-1.5 px-3 text-xs font-medium">
                {backtestRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3 fill-current" />}
                {backtestRunning ? "Running" : "Run Backtest"}
              </Button>
            )}

            <div className="h-3.5 w-px bg-border" />

            <Button variant="ghost" size="icon" className="h-7 w-7" aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>

            <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="Open console" onClick={() => setConsoleOpen(true)}><Bell className="h-4 w-4" /></Button>
            <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={() => { if (confirm('Sign out?')) logout(); }}>
              <User className="h-3.5 w-3.5" />
              <span>{username}</span>
            </Button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-5 max-w-[1400px] mx-auto w-full">
          {loading ? (
            <div className="space-y-6 p-1">
              <div className="grid grid-cols-4 gap-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-24 rounded-lg" />
                ))}
              </div>
              <Skeleton className="h-[300px] rounded-lg" />
              <div className="grid grid-cols-3 gap-4">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-48 rounded-lg" />
                ))}
              </div>
            </div>
          ) : (
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <Outlet />
              </Suspense>
            </ErrorBoundary>
          )}
        </main>

        <ModelSelector models={models} selectedModelId={selectedModelId} onSelect={setSelectedModelId} onDelete={handleDeleteModel} open={selectorOpen} onOpenChange={setSelectorOpen} />

        <ConsoleModal
          isOpen={consoleOpen}
          onClose={() => setConsoleOpen(false)}
          warnings={qualityWarnings}
        />
      </div>
    </div>
  );
}

function DashboardRoute({ models, selectedModelId, startUpdateData }: { models: ModelData[]; selectedModelId: string; startUpdateData: () => Promise<void> }) {
  const selectedModel = models.find(m => m.id === selectedModelId);
  if (selectedModel) {
    return <Dashboard data={selectedModel.backtest} params={selectedModel.params} />;
  }
  return (
    <div className="flex flex-col items-center justify-center py-32 bg-muted/10 rounded-3xl border-2 border-dashed border-border/50">
      <p className="text-muted-foreground font-medium mb-6">No model data found in the local registry.</p>
      <Button onClick={startUpdateData} variant="outline" className="rounded-full px-8 uppercase font-black text-[10px] tracking-widest">Bootstrap Data</Button>
    </div>
  );
}

function CompareRoute({ models }: { models: ModelData[] }) {
  const location = useLocation();
  const state = location.state as { preselectedIds?: string[] } | null;
  return <ComparePage models={models} preselectedIds={state?.preselectedIds} />;
}

function ArenaRoute() {
  const navigate = useNavigate();
  return <ArenaPage onCompare={(runId) => navigate('/compare', { state: { preselectedIds: [runId] } })} />;
}

function App() {
  const { authHeader } = useAuth();

  // Wire up auth header provider for apiFetch
  useLayoutEffect(() => {
    setAuthHeaderProvider(authHeader);
    return () => setAuthHeaderProvider(null);
  }, [authHeader]);

  return (
    <AuthGuard>
      <AuthenticatedApp />
    </AuthGuard>
  );
}

function AuthenticatedApp() {
  const [models, setModels] = useState<ModelData[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string>("");
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const { setLatestCalendarDay, setQualityStatus, setQualityWarnings, setActiveJobsCount, setDataGeneratedAt, setApiError, setUsername, setSelectedModelId: setGlobalModelId, setSelectedModelMarket } = useGlobalStore();

  const [backtestJobId, setBacktestJobId] = useState<string>("");
  const [backtestRunning, setBacktestRunning] = useState(false);
  const [dataJobId, setDataJobId] = useState<string>("");

  // Sync model selection to global store so StockTerminal can access it
  useEffect(() => {
    setGlobalModelId(selectedModelId);
    const selectedModel = models.find(m => m.id === selectedModelId);
    if (selectedModel?.market) {
      setSelectedModelMarket(selectedModel.market);
    }
  }, [selectedModelId, models, setGlobalModelId, setSelectedModelMarket]);

  useEffect(() => {
    const loadData = async () => {
      try {
        const resp = await apiFetch(artifactUrl.dashboardDb, { cache: "no-store" });
        if (resp.ok) {
          const json = await resp.json();
          const parsed = parseQlibData(json);
          if (parsed.length > 0) {
            setModels(parsed);
            setSelectedModelId(parsed[0].id);
          }
          if (json.generated_at) setDataGeneratedAt(String(json.generated_at));
          setApiError(null);
        } else {
          setApiError(`Server error: HTTP ${resp.status}`);
        }
      } catch (err) {
        setApiError("Cannot reach server. Check if the backend is running.");
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, []);

  const loadDataStatus = async () => {
    try {
      const resp = await apiFetch("/api/data/status", { cache: "no-store" });
      if (!resp.ok) return;
      const json = await resp.json();
      setLatestCalendarDay(String(json?.data?.latest_calendar_day || ""));
      setQualityStatus(json?.data?.quality_status || "ok");
      setQualityWarnings(json?.data?.quality_warnings || []);
    } catch { /* server not running */ }
  };

  const loadActiveJobs = async () => {
    try {
      const resp = await apiFetch("/api/jobs?status=running", { cache: "no-store" });
      if (!resp.ok) return;
      const json = await resp.json();
      setActiveJobsCount((json?.jobs || []).length);
    } catch { setActiveJobsCount(0); }
  };

  useEffect(() => {
    loadDataStatus();
    loadActiveJobs();
    apiFetch("/api/system/me", { cache: "no-store" })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (data?.username) setUsername(data.username); })
      .catch(() => { /* server not running */ });
    const timer = setInterval(() => {
      loadDataStatus();
      loadActiveJobs();
    }, 10000);
    return () => clearInterval(timer);
  }, []);

  const refreshFromServer = async (opts?: { selectLatest?: boolean }) => {
    try {
      const resp = await apiFetch(artifactUrl.dashboardDb, { cache: "no-store" });
      if (!resp.ok) return false;
      const json = await resp.json();
      const parsed = parseQlibData(json);
      if (parsed.length === 0) return false;
      setModels(parsed);
      setSelectedModelId((cur) => {
        if (opts?.selectLatest) return parsed[0].id;
        return parsed.some((m) => m.id === cur) ? cur : parsed[0].id;
      });
      await loadDataStatus();
      return true;
    } catch { return false; }
  };

  const startBacktestForSelectedMarket = async () => {
    const selectedModel = models.find(m => m.id === selectedModelId);
    if (!selectedModel) return;
    const hasModelBinding = Boolean(selectedModel.params?.model_path) || Boolean(selectedModel.params?.source_model_path);
    if (!hasModelBinding) {
      console.warn("This run does not have a recorded model binding.");
      return;
    }
    const market = String(selectedModel.market || "").toLowerCase();

    setBacktestRunning(true);
    try {
      const resp = await apiFetch("/api/backtest/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          market, model_type: "lgbm", mode: "rebacktest",
          run_id: selectedModel.id, start: "2025-01-01", end: "latest",
        }),
      });
      if (resp.ok) {
        const json = await resp.json();
        setBacktestJobId(json.job_id);
      } else { setBacktestRunning(false); }
    } catch { setBacktestRunning(false); }
  };

  useEffect(() => {
    if (!backtestJobId) return;
    const timer = window.setInterval(async () => {
      const resp = await apiFetch(`/api/jobs/${encodeURIComponent(backtestJobId)}`);
      if (!resp.ok) return;
      const json = await resp.json();
      const status = json?.job?.status || "";
      if (status === "succeeded" || status === "failed") {
        window.clearInterval(timer);
        setBacktestRunning(false);
        setBacktestJobId("");
        await refreshFromServer({ selectLatest: status === "succeeded" });
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [backtestJobId]);

  const startUpdateData = async () => {
    try {
      const resp = await apiFetch("/api/data/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ full: false, lookback_days: 30 }),
      });
      if (resp.ok) {
        const json = await resp.json();
        setDataJobId(json.job_id);
      }
    } catch { /* ignore */ }
  };

  useEffect(() => {
    if (!dataJobId) return;
    const timer = window.setInterval(async () => {
      const resp = await apiFetch(`/api/jobs/${encodeURIComponent(dataJobId)}`);
      if (!resp.ok) return;
      const json = await resp.json();
      const status = json?.job?.status || "";
      if (status === "succeeded" || status === "failed") {
        window.clearInterval(timer);
        setDataJobId("");
        await refreshFromServer();
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [dataJobId]);

  const handleDeleteModel = async (id: string) => {
    try {
      const resp = await apiFetch("/api/models/delete", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version_id: id })
      });
      if (resp.ok) {
        await refreshFromServer({ selectLatest: true });
      }
    } catch { /* ignore */ }
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
            startBacktestForSelectedMarket={startBacktestForSelectedMarket}
            backtestRunning={backtestRunning}
            handleDeleteModel={handleDeleteModel}
            loading={loading}
          />
        }>
          <Route index element={<DashboardRoute models={models} selectedModelId={selectedModelId} startUpdateData={startUpdateData} />} />
          <Route path="agent" element={<AgentControlCenter models={models} />} />
          <Route path="dashboard" element={<DashboardRoute models={models} selectedModelId={selectedModelId} startUpdateData={startUpdateData} />} />
          <Route path="terminal" element={<StockTerminal />} />
          <Route path="backtest" element={<BacktestPage />} />
          <Route path="arena" element={<ArenaRoute />} />
          <Route path="models" element={<ModelsPage />} />
          <Route path="compare" element={<CompareRoute models={models} />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="data" element={<DataPage />} />
          <Route path="factors" element={<FactorPage />} />
          <Route path="factor-registry" element={<FactorRegistryPage />} />
          <Route path="experiments" element={<ExperimentLogPage />} />
          <Route path="attribution" element={<AttributionPage />} />
          <Route path="strategy" element={<StrategyPage />} />
          <Route path="methodology" element={<MethodologyPage />} />
          <Route path="system" element={<SystemPage />} />
          <Route path="docs" element={<DocsPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}

export default App;
