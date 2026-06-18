import { X, Terminal, AlertCircle, Loader2, Clock, Send, Play, BarChart3, Database, HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface ConsoleModalProps {
  isOpen: boolean;
  onClose: () => void;
  warnings: string[];
}

type Job = {
  id: string;
  type: string;
  status: string;
  created_at: number;
  cmd?: string;
  commands?: string;
  name?: string;
  stdout?: string;
  error?: string;
};

export function ConsoleModal({ isOpen, onClose, warnings }: ConsoleModalProps) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(false);
  const [cmdInput, setCmdInput] = useState("");
  const [executing, setExecuting] = useState(false);

  const fetchJobs = async () => {
    setLoading(true);
    try {
      const resp = await fetch("/api/jobs?limit=20");
      const json = await resp.json();
      if (json.ok) {
        setJobs(json.jobs || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchJobs();
      const timer = setInterval(fetchJobs, 5000);
      return () => clearInterval(timer);
    }
  }, [isOpen]);

  const handleExecute = async () => {
    if (!cmdInput.trim()) return;
    setExecuting(true);
    try {
      // Parse command to match task+args structure if it matches a quick command
      let task = "backtest";
      let args: string[] = [];
      
      if (cmdInput.includes("train")) {
        task = "train";
        if (cmdInput.includes("--market cn")) args = ["--market", "cn", "--tag", "PROD_CN"];
        else args = ["--market", "us", "--tag", "PROD_V1"];
      } else if (cmdInput.includes("update_data")) {
        task = "data_update";
        args = ["--market", "all"];
      } else if (cmdInput.includes("arena_settle")) {
        task = "arena_settle";
        args = ["--market", "all"];
      } else {
        // Fallback for custom backtest
        task = "backtest";
        if (cmdInput.includes("--market cn")) args = ["--market", "cn"];
      }

      const resp = await fetch("/api/system/exec", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task, args })
      });
      if (resp.ok) {
        setCmdInput("");
        fetchJobs();
      } else {
        const err = await resp.json();
        alert(`Execution failed: ${err.detail || err.error || 'Unknown error'}`);
      }
    } catch (e) {
      alert(`Network error: ${e}`);
    } finally {
      setExecuting(false);
    }
  };

  const quickCommands = [
    { label: "Train US", cmd: "train --market us", icon: Play },
    { label: "Train CN", cmd: "train --market cn", icon: Play },
    { label: "Update Data", cmd: "data_update --market all", icon: Database },
    { label: "Full Backtest", cmd: "backtest --market us", icon: BarChart3 },
    { label: "Arena Settle", cmd: "arena_settle --market all", icon: BarChart3 },
    { label: "Clean Logs", cmd: "python scripts/cleanup_stuck_jobs.py", icon: X },
  ];

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-md animate-in fade-in duration-300 text-left">
      <div className="w-full max-w-4xl h-[85vh] flex flex-col bg-card rounded-2xl shadow-2xl border border-border overflow-hidden">
        <header className="p-6 border-b flex items-center justify-between bg-muted/20">
          <div className="flex items-center gap-4">
            <div className="p-2.5 bg-primary/10 rounded-xl text-primary">
              <Terminal className="h-6 w-6" />
            </div>
            <div>
              <h2 className="text-xl font-black tracking-tight uppercase">System Command Center</h2>
              <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em] text-left opacity-60">Engine Kernel & Task Scheduler</p>
            </div>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} className="rounded-full hover:bg-muted/50 transition-all">
            <X className="h-5 w-5" />
          </Button>
        </header>

        <div className="flex-1 overflow-y-auto p-8 space-y-10">
          {/* CLI Section */}
          <section className="space-y-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-black text-primary uppercase tracking-widest">
                <Terminal className="h-4 w-4" /> Interactive CLI
              </div>
              <div className="flex items-center gap-1.5 text-[9px] font-bold text-muted-foreground uppercase opacity-40">
                <HelpCircle className="h-3 w-3" /> Syntax: Python -m src.orchestrator [command]
              </div>
            </div>

            <div className="group flex gap-2 p-2 bg-slate-950 rounded-2xl border border-white/5 shadow-2xl transition-all focus-within:border-primary/30">
              <div className="flex items-center px-4 text-emerald-500 font-mono font-black select-none opacity-50 group-focus-within:opacity-100">$</div>
              <input
                type="text"
                value={cmdInput}
                onChange={(e) => setCmdInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleExecute()}
                placeholder="Enter kernel command or select from quick start below..."
                className="flex-1 bg-transparent border-none text-emerald-400 font-mono text-sm focus:ring-0 outline-none py-3"
              />
              <Button
                size="sm"
                onClick={handleExecute}
                disabled={executing || !cmdInput.trim()}
                className="rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-black uppercase text-[10px] gap-2 px-6 h-10 transition-all active:scale-95 shadow-lg shadow-emerald-900/20"
              >
                {executing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
                Deploy
              </Button>
            </div>

            <div className="flex flex-wrap gap-2 pt-1">
              {quickCommands.map((q, i) => (
                <button
                  key={i}
                  onClick={() => setCmdInput(q.cmd)}
                  className="flex items-center gap-2 px-4 py-2 bg-muted/30 hover:bg-muted border border-border/50 rounded-xl text-[10px] font-black uppercase tracking-tight text-muted-foreground transition-all hover:text-primary hover:border-primary/20 group"
                >
                  <q.icon className="h-3.5 w-3.5 opacity-40 group-hover:opacity-100" />
                  {q.label}
                </button>
              ))}
            </div>
          </section>

          <div className="h-px bg-border/50" />

          {/* Diagnostic Messages */}
          {warnings.length > 0 && (
            <section className="space-y-4">
              <div className="flex items-center gap-2 text-xs font-black text-rose-500 uppercase tracking-widest">
                <AlertCircle className="h-4 w-4" /> System Health Warnings
              </div>
              <div className="grid gap-3">
                {warnings.map((w, i) => (
                  <div key={i} className="p-4 bg-rose-500/5 border border-rose-500/10 rounded-2xl text-xs font-mono text-rose-600 flex items-start gap-4 shadow-sm">
                    <span className="opacity-30 font-black">0x{i.toString(16).padStart(2, '0')}</span>
                    <span className="leading-relaxed font-medium">{w}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Process History */}
          <section className="space-y-5 pb-10">
            <div className="flex items-center justify-between border-b border-border/50 pb-3">
              <div className="flex items-center gap-2 text-xs font-black text-blue-500 uppercase tracking-widest text-left">
                <Clock className="h-4 w-4" /> Live Process Monitor
              </div>
              <span className="text-[10px] font-black text-muted-foreground/40 uppercase tracking-widest">Recent 20 Threads</span>
            </div>

            <div className="space-y-3">
              {loading && jobs.length === 0 ? (
                <div className="py-20 flex flex-col items-center justify-center text-muted-foreground italic">
                  <Loader2 className="h-10 w-10 animate-spin mb-4 opacity-10" />
                  <span className="text-[10px] uppercase tracking-[0.3em] font-black">Syncing Process Bus...</span>
                </div>
              ) : jobs.length === 0 ? (
                <div className="py-20 flex flex-col items-center justify-center bg-muted/10 rounded-3xl border-2 border-dashed border-border/50">
                  <Terminal className="h-12 w-12 text-muted-foreground/10 mb-4" />
                  <p className="text-[10px] font-black text-muted-foreground uppercase tracking-widest italic text-center opacity-40">Zero active process instances detected</p>
                </div>
              ) : (
                jobs.map((j) => (
                  <div key={j.id} className={cn(
                    "group p-5 rounded-2xl border-2 transition-all shadow-sm",
                    j.status === 'running' ? "bg-primary/[0.03] border-primary/20 animate-pulse" :
                      j.status === 'failed' ? "bg-rose-500/[0.03] border-rose-500/20" : "bg-card border-border/40 hover:border-border"
                  )}>
                    <div className="flex items-start justify-between gap-6">
                      <div className="space-y-1.5 min-w-0">
                        <div className="flex items-center gap-3">
                          <span className="text-xs font-black uppercase tracking-widest text-left">{(j.name || j.type || 'Unknown Task').replace('_', ' ')}</span>
                          <Badge variant={j.status === 'running' ? 'default' : j.status === 'succeeded' ? 'outline' : 'destructive'} className="text-[8px] font-black h-4 px-2 uppercase border-none">
                            {j.status}
                          </Badge>
                        </div>
                        <p className="text-[9px] font-mono text-muted-foreground font-bold opacity-40 tracking-tighter text-left uppercase">PID: {j.id}</p>
                      </div>
                      <div className="text-[10px] font-black text-muted-foreground/60 uppercase whitespace-nowrap bg-muted/50 px-2 py-1 rounded">
                        {new Date(j.created_at * 1000).toLocaleTimeString()}
                      </div>
                    </div>

                    {(j.cmd || j.commands) && (
                      <div className="mt-4 p-4 bg-slate-950 rounded-xl text-[10px] font-mono text-emerald-400/80 overflow-x-auto whitespace-nowrap border border-white/5 shadow-inner">
                        <span className="text-gray-600 select-none mr-3 font-black">bash:~$</span>
                        {j.cmd || j.commands}
                      </div>
                    )}

                    {j.stdout && j.stdout.length > 0 && (
                      <div className="mt-1 p-4 bg-slate-950/50 rounded-xl text-[10px] font-mono text-slate-300 overflow-x-auto whitespace-pre-wrap border border-white/5 max-h-40 overflow-y-auto">
                        {j.stdout}
                      </div>
                    )}

                    {j.error && (
                      <div className="mt-3 text-[10px] font-mono text-rose-400 bg-rose-500/5 p-4 rounded-xl border border-rose-500/10 whitespace-pre-wrap leading-relaxed shadow-inner">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="font-black uppercase bg-rose-500 text-white px-1.5 py-0.5 rounded-[4px] text-[8px]">Crit</span>
                          <span className="font-black uppercase tracking-widest text-[9px] text-rose-500">Traceback / Error log</span>
                        </div>
                        {j.error}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </section>
        </div>

        <footer className="p-5 border-t bg-muted/20 flex justify-between items-center px-8">
          <div className="flex gap-6">
            <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest">
              <div className="h-2 w-2 rounded-full bg-emerald-500 shadow-sm shadow-emerald-500/50" />
              Engine: Synchronized
            </div>
            <div className="flex items-center gap-2 text-[10px] font-black uppercase border-l pl-6 border-border/50 tracking-widest">
              <Terminal className="h-3.5 w-3.5 text-muted-foreground opacity-50" />
              PID: ALPHA_ENGINE_DAEMON
            </div>
          </div>
          <Button size="sm" onClick={onClose} variant="outline" className="rounded-xl h-9 px-8 font-black uppercase tracking-widest text-[10px] transition-all hover:bg-muted active:scale-95 shadow-sm border-border/50">Exit Controller</Button>
        </footer>
      </div>
    </div>
  );
}
