diff --git a/qlib-dashboard/src/App.tsx b/qlib-dashboard/src/App.tsx
index e286819..d9cbb1e 100644
--- a/qlib-dashboard/src/App.tsx
+++ b/qlib-dashboard/src/App.tsx
@@ -63,8 +63,6 @@ function Layout({ models, selectedModelId, setSelectedModelId, selectorOpen, set
   setSelectorOpen: (open: boolean) => void;
   consoleOpen: boolean;
   setConsoleOpen: (open: boolean) => void;
-  startBacktestForSelectedMarket: () => Promise<void>;
-  backtestRunning: boolean;
   handleDeleteModel: (id: string) => Promise<void>;
   loading: boolean;
 }) {
@@ -119,13 +117,6 @@ function Layout({ models, selectedModelId, setSelectedModelId, selectorOpen, set
           </div>
 
           <div className="flex items-center gap-2">
-            {(currentPath === 'dashboard' || currentPath === '') && (
-              <Button size="sm" variant="default" onClick={startBacktestForSelectedMarket} disabled={backtestRunning} className="h-7 gap-1.5 px-3 text-xs font-medium">
-                {backtestRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3 fill-current" />}
-                {backtestRunning ? "Running" : "Run Backtest"}
-              </Button>
-            )}
-
             <div className="h-3.5 w-px bg-border" />
 
             <Button variant="ghost" size="icon" className="h-7 w-7" aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
@@ -176,17 +167,10 @@ function Layout({ models, selectedModelId, setSelectedModelId, selectorOpen, set
   );
 }
 
-function DashboardRoute({ models, selectedModelId, startUpdateData }: { models: ModelData[]; selectedModelId: string; startUpdateData: () => Promise<void> }) {
-  const selectedModel = models.find(m => m.id === selectedModelId);
-  if (selectedModel) {
-    return <Dashboard data={selectedModel.backtest} params={selectedModel.params} />;
-  }
-  return (
-    <div className="flex flex-col items-center justify-center py-32 bg-muted/10 rounded-3xl border-2 border-dashed border-border/50">
-      <p className="text-muted-foreground font-medium mb-6">No model data found in the local registry.</p>
-      <Button onClick={startUpdateData} variant="outline" className="rounded-full px-8 uppercase font-black text-[10px] tracking-widest">Bootstrap Data</Button>
-    </div>
-  );
+import { TrueDashboard } from './components/TrueDashboard';
+
+function DashboardRoute({ startUpdateData }: { startUpdateData: () => Promise<void> }) {
+  return <TrueDashboard startUpdateData={startUpdateData} />;
 }
 
 function CompareRoute({ models }: { models: ModelData[] }) {
@@ -216,187 +200,40 @@ function App() {
   );
 }
 
+import { useAppBootstrap } from './hooks/useAppBootstrap';
+import { backtestApi } from './api/backtestApi';
+import { dataApi } from './api/dataApi';
+
 function AuthenticatedApp() {
-  const [models, setModels] = useState<ModelData[]>([]);
-  const [selectedModelId, setSelectedModelId] = useState<string>("");
   const [selectorOpen, setSelectorOpen] = useState(false);
   const [consoleOpen, setConsoleOpen] = useState(false);
-  const [loading, setLoading] = useState(true);
-  const { setLatestCalendarDay, setQualityStatus, setQualityWarnings, setActiveJobsCount, setDataGeneratedAt, setApiError, setUsername, setSelectedModelId: setGlobalModelId, setSelectedModelMarket } = useGlobalStore();
-
-  const [backtestJobId, setBacktestJobId] = useState<string>("");
-  const [backtestRunning, setBacktestRunning] = useState(false);
-  const [dataJobId, setDataJobId] = useState<string>("");
-
-  // Sync model selection to global store so StockTerminal can access it
-  useEffect(() => {
-    setGlobalModelId(selectedModelId);
-    const selectedModel = models.find(m => m.id === selectedModelId);
-    if (selectedModel?.market) {
-      setSelectedModelMarket(selectedModel.market);
-    }
-  }, [selectedModelId, models, setGlobalModelId, setSelectedModelMarket]);
-
-  useEffect(() => {
-    const loadData = async () => {
-      try {
-        const resp = await apiFetch(artifactUrl.dashboardDb, { cache: "no-store" });
-        if (resp.ok) {
-          const json = await resp.json();
-          const parsed = parseQlibData(json);
-          if (parsed.length > 0) {
-            setModels(parsed);
-            setSelectedModelId(parsed[0].id);
-          }
-          if (json.generated_at) setDataGeneratedAt(String(json.generated_at));
-          setApiError(null);
-        } else {
-          setApiError(`Server error: HTTP ${resp.status}`);
-        }
-      } catch (err) {
-        setApiError("Cannot reach server. Check if the backend is running.");
-      } finally {
-        setLoading(false);
-      }
-    };
-    loadData();
-  }, []);
-
-  const loadDataStatus = async () => {
-    try {
-      const resp = await apiFetch("/api/data/status", { cache: "no-store" });
-      if (!resp.ok) return;
-      const json = await resp.json();
-      setLatestCalendarDay(String(json?.data?.latest_calendar_day || ""));
-      setQualityStatus(json?.data?.quality_status || "ok");
-      setQualityWarnings(json?.data?.quality_warnings || []);
-    } catch { /* server not running */ }
-  };
+  const { qualityWarnings } = useGlobalStore();
 
-  const loadActiveJobs = async () => {
-    try {
-      const resp = await apiFetch("/api/jobs?status=running", { cache: "no-store" });
-      if (!resp.ok) return;
-      const json = await resp.json();
-      setActiveJobsCount((json?.jobs || []).length);
-    } catch { setActiveJobsCount(0); }
-  };
+  const {
+    loading,
+    models,
+    selectedModelId,
+    setSelectedModelId,
+    fetchModels,
+    deleteModel,
+    jobs: { isPolling: jobsPolling, submitAndPoll }
+  } = useAppBootstrap();
 
-  useEffect(() => {
-    loadDataStatus();
-    loadActiveJobs();
-    apiFetch("/api/system/me", { cache: "no-store" })
-      .then((r) => r.ok ? r.json() : null)
-      .then((data) => { if (data?.username) setUsername(data.username); })
-      .catch(() => { /* server not running */ });
-    const timer = setInterval(() => {
-      loadDataStatus();
-      loadActiveJobs();
-    }, 10000);
-    return () => clearInterval(timer);
-  }, []);
-
-  const refreshFromServer = async (opts?: { selectLatest?: boolean }) => {
-    try {
-      const resp = await apiFetch(artifactUrl.dashboardDb, { cache: "no-store" });
-      if (!resp.ok) return false;
-      const json = await resp.json();
-      const parsed = parseQlibData(json);
-      if (parsed.length === 0) return false;
-      setModels(parsed);
-      setSelectedModelId((cur) => {
-        if (opts?.selectLatest) return parsed[0].id;
-        return parsed.some((m) => m.id === cur) ? cur : parsed[0].id;
-      });
-      await loadDataStatus();
-      return true;
-    } catch { return false; }
-  };
-
-  const startBacktestForSelectedMarket = async () => {
-    const selectedModel = models.find(m => m.id === selectedModelId);
-    if (!selectedModel) return;
-    const hasModelBinding = Boolean(selectedModel.params?.model_path) || Boolean(selectedModel.params?.source_model_path);
-    if (!hasModelBinding) {
-      console.warn("This run does not have a recorded model binding.");
-      return;
-    }
-    const market = String(selectedModel.market || "").toLowerCase();
-
-    setBacktestRunning(true);
-    try {
-      const resp = await apiFetch("/api/backtest/run", {
-        method: "POST",
-        headers: { "Content-Type": "application/json" },
-        body: JSON.stringify({
-          market, model_type: "lgbm", mode: "rebacktest",
-          run_id: selectedModel.id, start: "2025-01-01", end: "latest",
-        }),
-      });
-      if (resp.ok) {
-        const json = await resp.json();
-        setBacktestJobId(json.job_id);
-      } else { setBacktestRunning(false); }
-    } catch { setBacktestRunning(false); }
-  };
-
-  useEffect(() => {
-    if (!backtestJobId) return;
-    const timer = window.setInterval(async () => {
-      const resp = await apiFetch(`/api/jobs/${encodeURIComponent(backtestJobId)}`);
-      if (!resp.ok) return;
-      const json = await resp.json();
-      const status = json?.job?.status || "";
-      if (status === "succeeded" || status === "failed") {
-        window.clearInterval(timer);
-        setBacktestRunning(false);
-        setBacktestJobId("");
-        await refreshFromServer({ selectLatest: status === "succeeded" });
-      }
-    }, 2000);
-    return () => window.clearInterval(timer);
-  }, [backtestJobId]);
+  // removed backtestRunning state
 
   const startUpdateData = async () => {
     try {
-      const resp = await apiFetch("/api/data/update", {
-        method: "POST",
-        headers: { "Content-Type": "application/json" },
-        body: JSON.stringify({ full: false, lookback_days: 30 }),
-      });
-      if (resp.ok) {
-        const json = await resp.json();
-        setDataJobId(json.job_id);
-      }
-    } catch { /* ignore */ }
+      await submitAndPoll(
+        () => dataApi.updateData(false, 30),
+        () => fetchModels()
+      );
+    } catch {
+      /* ignore */
+    }
   };
 
-  useEffect(() => {
-    if (!dataJobId) return;
-    const timer = window.setInterval(async () => {
-      const resp = await apiFetch(`/api/jobs/${encodeURIComponent(dataJobId)}`);
-      if (!resp.ok) return;
-      const json = await resp.json();
-      const status = json?.job?.status || "";
-      if (status === "succeeded" || status === "failed") {
-        window.clearInterval(timer);
-        setDataJobId("");
-        await refreshFromServer();
-      }
-    }, 2000);
-    return () => window.clearInterval(timer);
-  }, [dataJobId]);
-
   const handleDeleteModel = async (id: string) => {
-    try {
-      const resp = await apiFetch("/api/models/delete", {
-        method: "POST", headers: { "Content-Type": "application/json" },
-        body: JSON.stringify({ version_id: id })
-      });
-      if (resp.ok) {
-        await refreshFromServer({ selectLatest: true });
-      }
-    } catch { /* ignore */ }
+    await deleteModel(id);
   };
 
   return (
@@ -411,15 +248,13 @@ function AuthenticatedApp() {
             setSelectorOpen={setSelectorOpen}
             consoleOpen={consoleOpen}
             setConsoleOpen={setConsoleOpen}
-            startBacktestForSelectedMarket={startBacktestForSelectedMarket}
-            backtestRunning={backtestRunning}
             handleDeleteModel={handleDeleteModel}
             loading={loading}
           />
         }>
-          <Route index element={<DashboardRoute models={models} selectedModelId={selectedModelId} startUpdateData={startUpdateData} />} />
+          <Route index element={<DashboardRoute startUpdateData={startUpdateData} />} />
           <Route path="agent" element={<AgentControlCenter models={models} />} />
-          <Route path="dashboard" element={<DashboardRoute models={models} selectedModelId={selectedModelId} startUpdateData={startUpdateData} />} />
+          <Route path="dashboard" element={<DashboardRoute startUpdateData={startUpdateData} />} />
           <Route path="terminal" element={<StockTerminal />} />
           <Route path="backtest" element={<BacktestPage />} />
           <Route path="arena" element={<ArenaRoute />} />
diff --git a/qlib-dashboard/src/hooks/useAppBootstrap.ts b/qlib-dashboard/src/hooks/useAppBootstrap.ts
new file mode 100644
index 0000000..2ccddb6
--- /dev/null
+++ b/qlib-dashboard/src/hooks/useAppBootstrap.ts
@@ -0,0 +1,54 @@
+import { useState, useEffect } from 'react';
+import { useGlobalStore } from '@/store/globalStore';
+import { apiClient } from '@/lib/api-client';
+import { useModels } from './useModels';
+import { useJobs } from './useJobs';
+import { useDataStatus } from './useDataStatus';
+
+export function useAppBootstrap() {
+  const [loading, setLoading] = useState(true);
+  const { setApiError, setUsername } = useGlobalStore();
+  
+  const { models, selectedModelId, setSelectedModelId, fetchModels, deleteModel } = useModels();
+  const { activeJobId, isPolling, startPolling, submitAndPoll, pollActiveJobsCount } = useJobs();
+  const { loadDataStatus } = useDataStatus();
+
+  useEffect(() => {
+    const bootstrap = async () => {
+      try {
+        setLoading(true);
+        // Load data status and models in parallel
+        await Promise.all([
+          loadDataStatus(),
+          fetchModels(),
+          pollActiveJobsCount(),
+          apiClient.get<{ username: string }>('/api/system/me').then(data => {
+            if (data?.username) setUsername(data.username);
+          }).catch(() => {})
+        ]);
+        setApiError(null);
+      } catch (err) {
+        setApiError("Cannot reach server. Check if the backend is running.");
+      } finally {
+        setLoading(false);
+      }
+    };
+    
+    bootstrap();
+  }, [loadDataStatus, fetchModels, pollActiveJobsCount, setApiError, setUsername]);
+
+  return {
+    loading,
+    models,
+    selectedModelId,
+    setSelectedModelId,
+    fetchModels,
+    deleteModel,
+    jobs: {
+      activeJobId,
+      isPolling,
+      startPolling,
+      submitAndPoll
+    }
+  };
+}
diff --git a/qlib-dashboard/src/hooks/useDataStatus.ts b/qlib-dashboard/src/hooks/useDataStatus.ts
new file mode 100644
index 0000000..e2a5399
--- /dev/null
+++ b/qlib-dashboard/src/hooks/useDataStatus.ts
@@ -0,0 +1,37 @@
+import { useEffect, useCallback } from 'react';
+import { useGlobalStore } from '@/store/globalStore';
+import { dataApi } from '@/api/dataApi';
+
+export function useDataStatus() {
+  const { 
+    setLatestCalendarDay, 
+    setQualityStatus, 
+    setQualityWarnings,
+    setDataGeneratedAt
+  } = useGlobalStore();
+
+  const loadDataStatus = useCallback(async () => {
+    try {
+      const resp = await dataApi.getStatus();
+      const statusData = resp.data;
+      if (statusData) {
+        setLatestCalendarDay(String(statusData.latest_calendar_day || ""));
+        setQualityStatus(statusData.quality_status || "ok");
+        setQualityWarnings(statusData.quality_warnings || []);
+        if (statusData.dashboard_generated_at) {
+          setDataGeneratedAt(String(statusData.dashboard_generated_at));
+        }
+      }
+    } catch {
+      // server not running or error
+    }
+  }, [setLatestCalendarDay, setQualityStatus, setQualityWarnings, setDataGeneratedAt]);
+
+  useEffect(() => {
+    loadDataStatus();
+    const timer = setInterval(loadDataStatus, 10000);
+    return () => clearInterval(timer);
+  }, [loadDataStatus]);
+
+  return { loadDataStatus };
+}
diff --git a/qlib-dashboard/src/hooks/useJobs.ts b/qlib-dashboard/src/hooks/useJobs.ts
new file mode 100644
index 0000000..f7b3acc
--- /dev/null
+++ b/qlib-dashboard/src/hooks/useJobs.ts
@@ -0,0 +1,74 @@
+import { useState, useEffect, useCallback } from 'react';
+import { jobsApi, JobEnvelope } from '@/api/jobsApi';
+import { useGlobalStore } from '@/store/globalStore';
+
+export function useJobs() {
+  const [activeJobId, setActiveJobId] = useState<string | null>(null);
+  const [isPolling, setIsPolling] = useState(false);
+  const { setActiveJobsCount } = useGlobalStore();
+
+  const pollActiveJobsCount = useCallback(async () => {
+    try {
+      const resp = await jobsApi.getActiveJobs();
+      setActiveJobsCount(resp.jobs?.length || 0);
+    } catch {
+      setActiveJobsCount(0);
+    }
+  }, [setActiveJobsCount]);
+
+  useEffect(() => {
+    pollActiveJobsCount();
+    const timer = setInterval(pollActiveJobsCount, 10000);
+    return () => clearInterval(timer);
+  }, [pollActiveJobsCount]);
+
+  const startPolling = useCallback((jobId: string, onComplete?: (status: string) => void) => {
+    setActiveJobId(jobId);
+    setIsPolling(true);
+    
+    const timer = setInterval(async () => {
+      try {
+        const resp = await jobsApi.getJob(jobId);
+        const status = resp.job?.status || "";
+        if (status === "succeeded" || status === "failed") {
+          clearInterval(timer);
+          setIsPolling(false);
+          setActiveJobId(null);
+          pollActiveJobsCount();
+          if (onComplete) onComplete(status);
+        }
+      } catch (e) {
+        // ignore network error during polling
+      }
+    }, 2000);
+
+    // Initial check
+    pollActiveJobsCount();
+
+    return () => clearInterval(timer);
+  }, [pollActiveJobsCount]);
+
+  const submitAndPoll = useCallback(async (
+    submitFn: () => Promise<JobEnvelope>, 
+    onComplete?: (status: string) => void
+  ) => {
+    try {
+      const envelope = await submitFn();
+      if (envelope?.job_id) {
+        startPolling(envelope.job_id, onComplete);
+      }
+      return envelope;
+    } catch (e) {
+      console.error("Job submission failed", e);
+      throw e;
+    }
+  }, [startPolling]);
+
+  return {
+    activeJobId,
+    isPolling,
+    startPolling,
+    submitAndPoll,
+    pollActiveJobsCount
+  };
+}
diff --git a/qlib-dashboard/src/hooks/useModels.ts b/qlib-dashboard/src/hooks/useModels.ts
new file mode 100644
index 0000000..a9b9c80
--- /dev/null
+++ b/qlib-dashboard/src/hooks/useModels.ts
@@ -0,0 +1,76 @@
+import { useState, useCallback } from 'react';
+import { modelsApi } from '@/api/modelsApi';
+import { parseQlibData, ModelData } from '@/lib/data-parser';
+import { useGlobalStore } from '@/store/globalStore';
+
+export function useModels() {
+  const [models, setModels] = useState<ModelData[]>([]);
+  const [selectedModelId, setSelectedModelIdState] = useState<string>("");
+  const { setSelectedModelId: setGlobalModelId, setSelectedModelMarket } = useGlobalStore();
+
+  const setSelectedModelId = useCallback((id: string) => {
+    setSelectedModelIdState(id);
+    setGlobalModelId(id);
+    const selectedModel = models.find(m => m.id === id);
+    if (selectedModel?.market) {
+      setSelectedModelMarket(selectedModel.market);
+    }
+  }, [models, setGlobalModelId, setSelectedModelMarket]);
+
+  const fetchModels = useCallback(async (opts?: { selectLatest?: boolean }) => {
+    try {
+      const json = await modelsApi.getDashboardDb();
+      const parsed = parseQlibData(json);
+      setModels(parsed);
+      
+      if (parsed.length > 0) {
+        if (opts?.selectLatest) {
+          setSelectedModelId(parsed[0].id);
+        } else {
+          // preserve selection or pick first
+          setSelectedModelIdState(prev => {
+            const stillExists = parsed.some(m => m.id === prev);
+            const nextId = stillExists ? prev : parsed[0].id;
+            
+            // manually sync global since we are in state setter
+            setGlobalModelId(nextId);
+            const m = parsed.find(x => x.id === nextId);
+            if (m?.market) setSelectedModelMarket(m.market);
+            
+            return nextId;
+          });
+        }
+      } else {
+        setModels([]);
+        setSelectedModelIdState("");
+        setGlobalModelId("");
+        setSelectedModelMarket("US");
+      }
+      return parsed;
+    } catch (e) {
+      console.error("Failed to fetch models", e);
+      return null;
+    }
+  }, [setGlobalModelId, setSelectedModelMarket]);
+
+  const deleteModel = useCallback(async (versionId: string) => {
+    try {
+      const resp = await modelsApi.deleteModel(versionId);
+      if (resp.ok) {
+        await fetchModels({ selectLatest: true });
+        return true;
+      }
+      return false;
+    } catch {
+      return false;
+    }
+  }, [fetchModels]);
+
+  return {
+    models,
+    selectedModelId,
+    setSelectedModelId,
+    fetchModels,
+    deleteModel
+  };
+}
