import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Save, FileCode, CheckCircle2, AlertCircle, RefreshCw, Play, BarChart3, Info, BookOpen, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function StrategyPage() {
  const [files, setFiles] = useState<string[]>([]);
  const [selectedFile, setSelectedFile] = useState<string>("");
  const [content, setContent] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ type: 'ok' | 'error', msg: string } | null>(null);

  const loadFileList = async () => {
    try {
      const resp = await fetch("/api/strategy/list");
      const json = await resp.json();
      if (json.ok) {
        setFiles(json.files);
        if (json.files.length > 0 && !selectedFile) {
          setSelectedFile(json.files[0]);
        }
      }
    } catch (e) { console.error(e); }
  };

  const loadFileContent = async (filename: string) => {
    setLoading(true);
    try {
      const resp = await fetch(`/api/strategy/content/${filename}`);
      const json = await resp.json();
      if (json.ok) {
        setContent(json.content);
      }
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { loadFileList(); }, []);
  useEffect(() => { if (selectedFile) loadFileContent(selectedFile); }, [selectedFile]);

  const handleSave = async () => {
    if (!selectedFile) return;
    setSaving(true);
    setStatus(null);
    try {
      const resp = await fetch("/api/strategy/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: selectedFile, content })
      });
      const json = await resp.json();
      if (json.ok) {
        setStatus({ type: 'ok', msg: "Kernel configuration persistent." });
      } else {
        setStatus({ type: 'error', msg: json.error || "Failed to save." });
      }
    } catch (e: any) {
      setStatus({ type: 'error', msg: e.message });
    } finally { setSaving(false); }
  };

  return (
    <div className="space-y-8 max-w-[1400px] mx-auto pb-20 text-left">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b pb-6">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-primary font-bold text-xs uppercase tracking-widest mb-1">
            <FileCode className="h-3.5 w-3.5" />
            Parameter Architecture
          </div>
          <h1 className="text-4xl font-black tracking-tight">Strategy Config Hub</h1>
          <p className="text-muted-foreground text-sm max-w-md">The source of truth for market workflows, model hyperparameters, and universe selection logic. Modify YAML files below to refine engine behavior.</p>
        </div>
        
        <div className="flex items-center gap-2">
          <Button onClick={loadFileList} variant="ghost" size="sm" className="h-9 gap-2 border border-border/50 font-bold uppercase text-[10px]">
            <RefreshCw className="h-3.5 w-3.5" /> Sync Files
          </Button>
          <Button onClick={handleSave} disabled={saving || !selectedFile} className="h-9 shadow-xl bg-primary hover:bg-primary/90 gap-2 px-6 font-black uppercase text-[10px] tracking-widest transition-all active:scale-95">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save & Sync
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        <div className="lg:col-span-1 space-y-6">
            <Card className="border-none shadow-lg bg-muted/30">
            <CardHeader className="pb-4">
                <CardTitle className="text-[10px] uppercase font-black tracking-widest text-muted-foreground flex items-center gap-2">
                    <BookOpen className="h-3.5 w-3.5" /> Model Configurations
                </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1">
                {files.map(f => (
                <button
                    key={f}
                    onClick={() => setSelectedFile(f)}
                    className={cn(
                    "w-full flex items-center gap-3 p-3 rounded-xl border-2 transition-all group text-left",
                    selectedFile === f ? "bg-background border-primary shadow-md scale-[1.02]" : "bg-transparent border-transparent hover:border-border hover:bg-muted/50"
                    )}
                >
                    <div className={cn("h-2 w-2 rounded-full shrink-0", selectedFile === f ? "bg-primary" : "bg-muted-foreground/30")} />
                    <span className="text-[11px] font-bold truncate tracking-tight">{f}</span>
                </button>
                ))}
            </CardContent>
            </Card>

            <div className="p-6 bg-slate-900 text-white rounded-2xl border border-white/10 space-y-5 shadow-2xl">
                <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-primary flex items-center gap-2">
                    <Info className="h-3.5 w-3.5" /> Workflow Guide
                </h4>
                <div className="space-y-4">
                    <div className="space-y-1.5">
                        <p className="text-[10px] font-black text-white/80 uppercase flex items-center gap-2"><Play className="h-3 w-3 text-emerald-400" /> Phase 1: Training</p>
                        <p className="text-[9px] leading-relaxed text-white/40 italic">
                            1. Modify hyperparameters in <span className="text-white/60">model</span> section.
                        </p>
                        <p className="text-[9px] leading-relaxed text-white/40 italic">
                            2. Click 'Save & Sync'.
                        </p>
                        <p className="text-[9px] leading-relaxed text-white/40 italic">
                            3. Use Console (top right) to run 'Train' command.
                        </p>
                    </div>
                    <div className="space-y-1.5 border-t border-white/5 pt-3">
                        <p className="text-[10px] font-black text-white/80 uppercase flex items-center gap-2"><BarChart3 className="h-3 w-3 text-blue-400" /> Phase 2: Backtest</p>
                        <p className="text-[9px] leading-relaxed text-white/40 italic">
                            1. Adjust <span className="text-white/60">backtest.start_time</span> in the YAML.
                        </p>
                        <p className="text-[9px] leading-relaxed text-white/40 italic">
                            2. Run backtest via Console or Dashboard 'Execute' button.
                        </p>
                    </div>
                </div>
            </div>
        </div>

        <div className="lg:col-span-3 space-y-6">
          {status && (
            <div className={cn(
              "flex items-center gap-3 p-4 rounded-xl border-2 animate-in fade-in slide-in-from-top-2",
              status.type === 'ok' ? "bg-green-500/5 border-green-500/20 text-green-600" : "bg-red-500/5 border-red-500/20 text-red-600"
            )}>
              {status.type === 'ok' ? <CheckCircle2 className="h-5 w-5" /> : <AlertCircle className="h-5 w-5" />}
              <span className="text-sm font-bold uppercase tracking-tight">{status.msg}</span>
            </div>
          )}

          <Card className="border-none shadow-2xl overflow-hidden bg-slate-950 ring-1 ring-white/5">
            <CardHeader className="bg-white/[0.02] border-b border-white/5 py-4 px-6 text-left">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="bg-white/10 p-1.5 rounded">
                        <FileCode className="h-4 w-4 text-primary" />
                    </div>
                    <div>
                        <CardTitle className="text-xs font-black text-white/90 uppercase tracking-widest">Source Buffer: {selectedFile}</CardTitle>
                        <p className="text-[9px] font-bold text-white/20 uppercase tracking-tight">Direct Kernel Access • YAML Mode</p>
                    </div>
                </div>
                <Badge variant="outline" className="text-[8px] border-white/10 text-white/40 font-mono">UTF-8 ENCODED</Badge>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {loading ? (
                <div className="h-[650px] flex items-center justify-center text-white/10">
                  <Loader2 className="h-10 w-10 animate-spin opacity-20" />
                </div>
              ) : (
                <textarea
                  className="w-full h-[650px] bg-transparent text-emerald-400 p-8 font-mono text-[11px] focus:ring-0 outline-none resize-none leading-relaxed selection:bg-primary/20"
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  spellCheck={false}
                />
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
