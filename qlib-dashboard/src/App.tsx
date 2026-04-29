import { useState, useEffect } from 'react';
import { parseQlibData, ModelData } from './lib/data-parser';
import { Dashboard } from './components/Dashboard';
import { ModelSelector } from './components/ModelSelector';
import { StrategyPage } from './pages/StrategyPage';
import { ComparePage } from './pages/ComparePage';
import { ArenaPage } from './pages/ArenaPage';
import { ReportsPage } from './pages/ReportsPage';
import { ModelsPage } from './pages/ModelsPage';
import { DataPage } from './pages/DataPage';
import { StockTerminal } from './pages/StockTerminal';
import { AgentControlCenter } from './pages/AgentControlCenter';
import { DocsPage } from './pages/DocsPage';
import { GlobalStatusBar } from './components/GlobalStatusBar';
import { Sidebar } from './components/Sidebar';
import { ConsoleModal } from './components/ConsoleModal';
import { List, Play, Loader2, Bell, User, Sun, Moon } from 'lucide-react';
import { Button } from "@/components/ui/button";
import { useGlobalStore } from './store/globalStore';

const DASHBOARD_DB_URL = "/artifacts/dashboard/dashboard_db.json";

function App() {
  const [models, setModels] = useState<ModelData[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string>("");
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<"control-center" | "dashboard" | "strategy" | "compare" | "arena" | "reports" | "models" | "data" | "terminal" | "docs">("control-center");

  const {
    latestCalendarDay, setLatestCalendarDay,
    qualityStatus, setQualityStatus,
    qualityWarnings, setQualityWarnings,
    activeJobsCount, setActiveJobsCount,
    theme, setTheme
  } = useGlobalStore();

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  // Cross-page state
  const [comparePreselect, setComparePreselect] = useState<string[]>([]);

  // Job states
  const [backtestJobId, setBacktestJobId] = useState<string>("");
  const [backtestRunning, setBacktestRunning] = useState(false);
  const [dataJobId, setDataJobId] = useState<string>("");

  useEffect(() => {
    const loadData = async () => {
      try {
        const resp = await fetch(DASHBOARD_DB_URL, { cache: "no-store" });
        if (resp.ok) {
          const json = await resp.json();
          const parsed = parseQlibData(json);
          if (parsed.length > 0) {
            setModels(parsed);
            setSelectedModelId(parsed[0].id);
          }
        }
      } catch (err) {
        console.error("Failed to load dashboard data:", err);
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, []);

  const loadDataStatus = async () => {
    try {
      const resp = await fetch("/api/data/status", { cache: "no-store" });
      if (!resp.ok) return;
      const json = await resp.json();
      setLatestCalendarDay(String(json?.data?.latest_calendar_day || ""));
      setQualityStatus(json?.data?.quality_status || "ok");
      setQualityWarnings(json?.data?.quality_warnings || []);
    } catch { /* server not running */ }
  };

  const loadActiveJobs = async () => {
    try {
      const resp = await fetch("/api/jobs?status=running", { cache: "no-store" });
      if (!resp.ok) return;
      const json = await resp.json();
      setActiveJobsCount((json?.jobs || []).length);
    } catch { setActiveJobsCount(0); }
  };

  useEffect(() => {
    loadDataStatus();
    loadActiveJobs();
    const timer = setInterval(() => {
      loadDataStatus();
      loadActiveJobs();
    }, 10000);
    return () => clearInterval(timer);
  }, []);

  const refreshFromServer = async (opts?: { selectLatest?: boolean }) => {
    try {
      const resp = await fetch(DASHBOARD_DB_URL, { cache: "no-store" });
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
    if (!selectedModel) return;
    const hasModelBinding = Boolean((selectedModel.params as any)?.model_path) || Boolean((selectedModel.params as any)?.source_model_path);
    if (!hasModelBinding) {
      console.warn("This run does not have a recorded model binding.");
      return;
    }
    const market = String(selectedModel.market || "").toLowerCase();

    setBacktestRunning(true);
    try {
      const resp = await fetch("/api/backtest/run", {
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
      const resp = await fetch(`/api/jobs/${encodeURIComponent(backtestJobId)}`);
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
      const resp = await fetch("/api/data/update", {
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
      const resp = await fetch(`/api/jobs/${encodeURIComponent(dataJobId)}`);
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

  const handleArenaCompare = (runId: string) => {
    setComparePreselect([runId]);
    setView("compare");
  };

  const selectedModel = models.find(m => m.id === selectedModelId);

  const handleDeleteModel = async (id: string) => {
    try {
      const resp = await fetch("/api/models/delete", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version_id: id })
      });
      if (resp.ok) {
        await refreshFromServer({ selectLatest: true });
      }
    } catch { /* ignore */ }
  };



  return (
    <div className="flex h-screen overflow-hidden bg-transparent">
      <Sidebar currentView={view} onNavigate={setView} />
      <div className="flex-1 flex flex-col min-w-0 bg-transparent relative z-0">
        <GlobalStatusBar
          latestCalendarDay={latestCalendarDay}
          qualityStatus={qualityStatus}
          warnings={qualityWarnings}
          activeJobsCount={activeJobsCount}
          onOpenConsole={() => setConsoleOpen(true)}
        />

        <header className="h-14 border-b bg-card/50 backdrop-blur-md sticky top-0 z-40 px-6 flex items-center justify-between">
          <div className="flex items-center gap-4 text-xs font-bold text-muted-foreground">
            <h2 className="uppercase tracking-widest">{view === 'dashboard' ? 'Backtest Insights' : view.replace('-', ' ')}</h2>
            {view === 'dashboard' && selectedModel && (
              <>
                <div className="h-4 w-px bg-border" />
                <Button variant="ghost" size="sm" onClick={() => setSelectorOpen(true)} className="text-[10px] font-mono h-7 gap-2 px-2 hover:bg-muted/50">
                  <List className="h-3 w-3" /> {selectedModel.name}
                </Button>
              </>
            )}
          </div>

          <div className="flex items-center gap-3">
            {view === 'dashboard' && (
              <Button size="sm" variant="default" onClick={startBacktestForSelectedMarket} disabled={backtestRunning} className="h-8 gap-2 px-4 shadow-sm text-xs font-bold uppercase tracking-tighter">
                {backtestRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3 fill-current" />}
                {backtestRunning ? `Running` : "Execute Backtest"}
              </Button>
            )}

            <div className="h-4 w-px bg-border mx-1" />

            <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
              {theme === 'dark' ? <Sun className="h-4 w-4 text-muted-foreground" /> : <Moon className="h-4 w-4 text-muted-foreground" />}
            </Button>

            <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onClick={() => setConsoleOpen(true)}><Bell className="h-4 w-4" /></Button>
            <Button variant="outline" size="sm" className="h-8 gap-2 rounded-full border-primary/20 hover:border-primary/50 transition-colors text-left">
              <User className="h-3.5 w-3.5" />
              <span className="text-[10px] font-black uppercase tracking-tight">Zhihao</span>
            </Button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-6 max-w-[1600px] mx-auto w-full">
          {loading ? (
            <div className="h-full flex items-center justify-center p-8">
              <div className="flex flex-col items-center gap-6 w-full max-w-3xl">
                <div className="flex items-center gap-4">
                  <Loader2 className="h-10 w-10 animate-spin text-primary opacity-40 mix-blend-screen" />
                  <p className="text-[10px] text-muted-foreground animate-pulse font-black uppercase tracking-widest">Warming Engines</p>
                </div>

                {/* Roadmap Item 51: Layout Shift Skeletons */}
                <div className="w-full grid grid-cols-3 gap-6">
                  <div className="h-40 rounded-3xl skeleton-shimmer" />
                  <div className="h-40 rounded-3xl skeleton-shimmer" />
                  <div className="h-40 rounded-3xl skeleton-shimmer" />
                </div>
                <div className="w-full h-64 rounded-3xl skeleton-shimmer mt-6" />
              </div>
            </div>
          ) : (
            <div className="animate-in fade-in slide-in-from-bottom-2 duration-700">
              {view === "control-center" ? <AgentControlCenter /> :
                view === "arena" ? <ArenaPage onCompare={handleArenaCompare} /> :
                  view === "terminal" ? <StockTerminal /> :
                    view === "reports" ? <ReportsPage /> :
                      view === "models" ? <ModelsPage /> :
                        view === "data" ? <DataPage /> :
                    view === "strategy" ? <StrategyPage /> :
                      view === "docs" ? <DocsPage /> :
                            view === "compare" ? <ComparePage models={models} preselectedIds={comparePreselect} /> :
                              selectedModel ? <Dashboard data={selectedModel.backtest} params={selectedModel.params} /> :
                                <div className="flex flex-col items-center justify-center py-32 bg-muted/10 rounded-3xl border-2 border-dashed border-border/50">
                                  <p className="text-muted-foreground font-medium mb-6">No model data found in the local registry.</p>
                                  <Button onClick={startUpdateData} variant="outline" className="rounded-full px-8 uppercase font-black text-[10px] tracking-widest">Bootstrap Data</Button>
                                </div>}
            </div>
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

export default App;
