import { useState, useEffect } from 'react';
import {
    BrainCircuit,
    Activity,
    Database,
    CheckCircle2,
    AlertTriangle
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ModelData, parseQlibData } from '@/lib/data-parser';
import { ComparePage } from '@/pages/ComparePage';
import { CopilotUI } from '@/components/CopilotUI';

const DASHBOARD_DB_URL = "/artifacts/dashboard/dashboard_db.json";
const THOUGHT_STREAM_URL = "/artifacts/agent_thought_stream.json";

interface AgentLog {
    id: string;
    date: string;
    agent: string;
    level: string;
    thought: string;
}

export function AgentControlCenter() {
    const [models, setModels] = useState<ModelData[]>([]);
    const [thoughtStream, setThoughtStream] = useState<AgentLog[]>([]);

    useEffect(() => {
        const loadData = async () => {
            try {
                const resp = await fetch(DASHBOARD_DB_URL, { cache: "no-store" });
                if (resp.ok) {
                    const json = await resp.json();
                    const parsed = parseQlibData(json);
                    setModels(parsed);
                }
            } catch (e) {
                console.error("Failed to load dashboard data", e);
            }
            try {
                const tsResp = await fetch(THOUGHT_STREAM_URL, { cache: "no-store" });
                if (tsResp.ok) {
                    const tsJson = await tsResp.json();
                    setThoughtStream(tsJson.reverse()); // Show newest first
                }
            } catch (e) {
                console.error("Failed to load thought stream", e);
            }
        };
        loadData();
        const interval = setInterval(loadData, 5000);
        return () => clearInterval(interval);
    }, []);
    return (
        <div className="flex flex-col gap-6 w-full animate-in fade-in zoom-in-95 duration-700">

            {/* Header Section */}
            <div className="flex items-center justify-between mb-2">
                <div>
                    <h1 className="text-3xl font-black tracking-tighter uppercase flex items-center gap-3">
                        <BrainCircuit className="w-8 h-8 text-primary" />
                        Control Center
                    </h1>
                    <p className="text-muted-foreground mt-1 tracking-widest text-xs font-semibold uppercase">
                        Agentic Alpha Engine • Multi-Agent Orchestration
                    </p>
                </div>
                <div className="flex gap-3">
                    <Button variant="outline" className="gap-2 rounded-full font-bold uppercase text-[10px] tracking-widest backdrop-blur-md bg-background/50 border-white/10 shadow-xl">
                        <Activity className="w-3 h-3 text-emerald-500" />
                        System Healthy
                    </Button>
                </div>
            </div>

            {/* Main Grid: Glassmorphism Layout */}
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 h-[75vh]">

                {/* Left Column: Thought Stream & Logs */}
                <div className="xl:col-span-1 glass-panel p-6 flex flex-col gap-4 overflow-hidden relative group">
                    <div className="absolute inset-0 bg-gradient-to-br from-primary/10 via-transparent to-transparent opacity-50 pointer-events-none" />

                    <div className="flex items-center justify-between z-10">
                        <h3 className="font-bold uppercase tracking-widest text-xs flex items-center gap-2 text-primary">
                            <BrainCircuit className="w-4 h-4" />
                            Thought Stream
                        </h3>
                        <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
                    </div>

                    <div className="flex-1 overflow-y-auto space-y-4 pr-2 z-10 custom-scrollbar">
                        {thoughtStream.length === 0 ? (
                            <div className="p-4 rounded-2xl bg-white/5 border border-white/5 backdrop-blur-sm transition-all text-center text-muted-foreground text-xs uppercase tracking-widest font-bold">
                                Awaiting Agent Activity...
                            </div>
                        ) : (
                            thoughtStream.map(log => {
                                const isRisk = log.agent.toLowerCase().includes('risk');
                                const isAlpha = log.agent.toLowerCase().includes('alpha');
                                const bgClass = isRisk ? 'bg-amber-500/10 hover:bg-amber-500/20' : isAlpha ? 'bg-emerald-500/10 hover:bg-emerald-500/20' : 'bg-white/5 hover:bg-white/10';
                                const borderClass = isRisk ? 'border-amber-500/20' : isAlpha ? 'border-emerald-500/20' : 'border-white/5';
                                const textClass = isRisk ? 'text-amber-500' : isAlpha ? 'text-emerald-500' : 'text-muted-foreground';
                                const dateStr = new Date(log.date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

                                return (
                                    <div key={log.id} className={`p-4 rounded-2xl border backdrop-blur-sm transition-all ${bgClass} ${borderClass}`}>
                                        <div className="flex items-center justify-between mb-2">
                                            <span className={`text-[10px] uppercase font-black tracking-widest ${textClass}`}>{log.agent}</span>
                                            <span className={`text-[10px] text-muted-foreground border px-2 py-0.5 rounded-full ${borderClass}`}>{dateStr}</span>
                                        </div>
                                        <p className={`text-sm font-medium leading-relaxed flex gap-2 ${isRisk ? 'text-amber-50' : isAlpha ? 'text-emerald-50' : 'text-foreground/90'}`}>
                                            {isRisk && <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />}
                                            {isAlpha && <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />}
                                            {log.thought}
                                        </p>
                                        {isAlpha && log.thought.includes("Requesting addition") && (
                                            <div className="mt-3 flex gap-2">
                                                <Button size="sm" className="h-7 text-[10px] uppercase tracking-wider font-bold bg-emerald-600 hover:bg-emerald-500 text-white border-0">Approve</Button>
                                                <Button size="sm" variant="outline" className="h-7 text-[10px] uppercase tracking-wider font-bold border-emerald-500/30 text-emerald-500 hover:bg-emerald-500/10">Ignore</Button>
                                            </div>
                                        )}
                                    </div>
                                );
                            })
                        )}
                    </div>
                </div>

                {/* Right Column: Evidence Canvas (Compare View Container) */}
                <div className="xl:col-span-2 glass-panel p-6 flex flex-col relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-96 h-96 bg-primary/20 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2 pointer-events-none" />

                    <div className="flex items-center justify-between mb-6 z-10">
                        <h3 className="font-bold uppercase tracking-widest text-xs flex items-center gap-2 text-foreground/80">
                            <Database className="w-4 h-4" />
                            Evidence Canvas
                        </h3>
                    </div>

                    <div className="flex-1 overflow-y-auto z-10 custom-scrollbar pr-2 mb-4">
                        {models.length === 0 ? (
                            <div className="text-center space-y-4 h-[200px] flex flex-col items-center justify-center">
                                <Activity className="w-12 h-12 text-muted-foreground/30 mx-auto animate-pulse" />
                                <p className="text-sm uppercase tracking-widest font-bold text-muted-foreground/50">
                                    Loading Evidence Canvas...
                                </p>
                            </div>
                        ) : (
                            <div className="h-[250px]">
                                <ComparePage models={models} compact={true} />
                            </div>
                        )}
                    </div>

                    {/* Add Copilot Chat UI directly below the Evidence Canvas */}
                    <div className="h-[400px] z-10 relative">
                        <CopilotUI />
                    </div>
                </div>

            </div>
        </div>
    );
}
