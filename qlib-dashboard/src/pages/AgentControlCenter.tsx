import { useState, useEffect } from 'react';
import {
    BrainCircuit,
    Activity,
    Database,
    CheckCircle2,
    AlertTriangle,
    Search,
    Shield,
    BarChart3,
    Cog,
    Send,
    Loader2
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ModelData } from '@/lib/data-parser';
import { ComparePage } from '@/pages/ComparePage';
import { artifactUrl } from '@/lib/artifacts';
import { apiFetch } from "@/lib/api";

interface AgentLog {
    id: string;
    date: string;
    agent: string;
    level: string;
    thought: string;
}

/** Safely format a timestamp string for display. Never returns "Invalid Date". */
function _safeFormatTime(ts: string | undefined | null): string {
    if (!ts) return "—";
    try {
        const d = new Date(ts);
        if (Number.isNaN(d.getTime())) {
            // Fall back to raw string (truncated) if parsing fails
            return ts.slice(0, 16);
        }
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
        return ts.slice(0, 16);
    }
}

interface ToolResult {
    ok: boolean;
    reply?: string;
    error?: string;
    [key: string]: unknown;
}

const quickActions = [
    { id: 'analyze-factors', label: 'Analyze Factors', icon: Search, endpoint: '/api/tools/analyze-factors', method: 'POST', body: { market: 'us' } },
    { id: 'check-data-quality', label: 'Check Data Quality', icon: Database, endpoint: '/api/tools/data-quality/us', method: 'GET', body: null },
    { id: 'assess-risk', label: 'Assess Risk', icon: Shield, endpoint: '/api/tools/assess-risk', method: 'POST', body: {} },
    { id: 'audit-run', label: 'Audit Run', icon: BarChart3, endpoint: '/api/tools/audit-run/latest', method: 'POST', body: null },
] as const;

export function AgentControlCenter({ models }: { models: ModelData[] }) {
    const [thoughtStream, setThoughtStream] = useState<AgentLog[]>([]);
    const [chatInput, setChatInput] = useState('');
    const [chatHistory, setChatHistory] = useState<{ role: 'user' | 'assistant'; text: string }[]>([]);
    const [loading, setLoading] = useState<string | null>(null);

    useEffect(() => {
        const loadThoughtStream = async () => {
            try {
                const tsResp = await apiFetch(artifactUrl.thoughtStream, { cache: "no-store" });
                if (tsResp.ok) {
                    const tsJson = await tsResp.json();
                    setThoughtStream(tsJson.reverse());
                }
            } catch (e) {
                console.error("Failed to load thought stream", e);
            }
        };
        loadThoughtStream();
        const interval = setInterval(loadThoughtStream, 5000);
        return () => clearInterval(interval);
    }, []);

    const callTool = async (endpoint: string, method: string, body: Record<string, unknown> | null, actionLabel: string) => {
        setLoading(actionLabel);
        try {
            const opts: RequestInit = { method, headers: { 'Content-Type': 'application/json' } };
            if (body && method !== 'GET') opts.body = JSON.stringify(body);
            const resp = await apiFetch(endpoint, opts);
            const data: ToolResult = await resp.json();
            const reply = data.reply || JSON.stringify(data, null, 2);
            setChatHistory(prev => [...prev, { role: 'user', text: `[${actionLabel}]` }, { role: 'assistant', text: reply }]);
        } catch (e: unknown) {
            setChatHistory(prev => [...prev, { role: 'user', text: `[${actionLabel}]` }, { role: 'assistant', text: `Error: ${e instanceof Error ? e.message : String(e)}` }]);
        } finally {
            setLoading(null);
        }
    };

    const handleQuickAction = (action: typeof quickActions[number]) => {
        callTool(action.endpoint, action.method, action.body, action.label);
    };

    const handleChat = async () => {
        const msg = chatInput.trim();
        if (!msg) return;
        setChatInput('');
        setChatHistory(prev => [...prev, { role: 'user', text: msg }]);
        setLoading('chat');
        try {
            const resp = await apiFetch('/api/tools/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: msg }),
            });
            const data = await resp.json();
            setChatHistory(prev => [...prev, { role: 'assistant', text: data.reply || JSON.stringify(data, null, 2) }]);
        } catch (e: unknown) {
            setChatHistory(prev => [...prev, { role: 'assistant', text: `Error: ${e instanceof Error ? e.message : String(e)}` }]);
        } finally {
            setLoading(null);
        }
    };

    return (
        <div className="flex flex-col gap-6 w-full animate-in fade-in zoom-in-95 duration-700">

            {/* Header Section */}
            <div className="flex items-center justify-between mb-2">
                <div>
                    <h1 className="text-3xl font-black tracking-tighter uppercase flex items-center gap-3">
                        <BrainCircuit className="w-8 h-8 text-primary" />
                        Research Assistant
                    </h1>
                    <p className="text-muted-foreground mt-1 tracking-widest text-xs font-semibold uppercase">
                        Unified AI Research Agent
                    </p>
                </div>
                <div className="flex gap-3">
                    <Button variant="outline" className="gap-2 rounded-full font-bold uppercase text-[10px] tracking-widest backdrop-blur-md bg-background/50 border-white/10 shadow-xl">
                        <Activity className="w-3 h-3 text-emerald-500" />
                        Online
                    </Button>
                </div>
            </div>

            {/* Main Grid */}
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 h-[75vh]">

                {/* Left Column: Thought Stream */}
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
                                // Normalized agent name: all entries are from the unified ResearchAssistant.
                                // Legacy multi-agent entries (Alpha, Risk, Governance, Developer) are
                                // preserved in the audit payload but displayed under the unified identity.
                                const agentLabel = "ResearchAssistant";
                                const bgClass = 'bg-emerald-500/10 hover:bg-emerald-500/20';
                                const borderClass = 'border-emerald-500/20';
                                const textClass = 'text-emerald-500';
                                // Defensive timestamp formatting: never render "Invalid Date"
                                const dateStr = _safeFormatTime(log.date);

                                return (
                                    <div key={log.id} className={`p-4 rounded-2xl border backdrop-blur-sm transition-all ${bgClass} ${borderClass}`}>
                                        <div className="flex items-center justify-between mb-2">
                                            <span className={`text-[10px] uppercase font-black tracking-widest ${textClass}`}>{agentLabel}</span>
                                            <span className={`text-[10px] text-muted-foreground border px-2 py-0.5 rounded-full ${borderClass}`}>{dateStr}</span>
                                        </div>
                                        <p className={`text-sm font-medium leading-relaxed flex gap-2 ${'text-emerald-50'}`}>
                                            <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
                                            {log.thought}
                                        </p>
                                    </div>
                                );
                            })
                        )}
                    </div>
                </div>

                {/* Right Column: Chat + Actions + Evidence Canvas */}
                <div className="xl:col-span-2 glass-panel p-6 flex flex-col relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-96 h-96 bg-primary/20 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2 pointer-events-none" />

                    {/* Quick Action Buttons */}
                    <div className="z-10 mb-4">
                        <h3 className="font-bold uppercase tracking-widest text-xs flex items-center gap-2 text-foreground/80 mb-3">
                            <Cog className="w-4 h-4" />
                            Quick Actions
                        </h3>
                        <div className="flex flex-wrap gap-2">
                            {quickActions.map((action) => {
                                const Icon = action.icon;
                                const isLoading = loading === action.label;
                                return (
                                    <Button
                                        key={action.id}
                                        variant="outline"
                                        size="sm"
                                        className="h-8 gap-1.5 text-[10px] uppercase tracking-wider font-bold"
                                        onClick={() => handleQuickAction(action)}
                                        disabled={loading !== null}
                                    >
                                        {isLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Icon className="h-3 w-3" />}
                                        {action.label}
                                    </Button>
                                );
                            })}
                        </div>
                    </div>

                    {/* Chat Area */}
                    <div className="flex-1 flex flex-col z-10 min-h-0">
                        <h3 className="font-bold uppercase tracking-widest text-xs flex items-center gap-2 text-foreground/80 mb-3">
                            <Database className="w-4 h-4" />
                            Chat
                        </h3>

                        <div className="flex-1 overflow-y-auto space-y-3 pr-2 mb-3 min-h-0 custom-scrollbar">
                            {chatHistory.length === 0 && (
                                <div className="text-center space-y-2 py-8">
                                    <Activity className="w-8 h-8 text-muted-foreground/30 mx-auto" />
                                    <p className="text-xs uppercase tracking-widest font-bold text-muted-foreground/50">
                                        Ask the Research Assistant anything
                                    </p>
                                </div>
                            )}
                            {chatHistory.map((msg, i) => (
                                <div key={i} className={`p-3 rounded-xl text-sm ${msg.role === 'user' ? 'bg-primary/10 ml-8 text-right' : 'bg-white/5 mr-8'}`}>
                                    <pre className="whitespace-pre-wrap text-xs font-mono text-left">{msg.text}</pre>
                                </div>
                            ))}
                            {loading === 'chat' && (
                                <div className="p-3 rounded-xl bg-white/5 mr-8 flex items-center gap-2">
                                    <Loader2 className="h-3 w-3 animate-spin" />
                                    <span className="text-xs text-muted-foreground">Thinking...</span>
                                </div>
                            )}
                        </div>

                        {/* Chat Input */}
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={chatInput}
                                onChange={(e) => setChatInput(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && handleChat()}
                                placeholder="Ask about factors, risk, data quality..."
                                className="flex-1 bg-background border rounded-lg px-3 py-2 text-sm outline-none focus:border-primary transition-colors"
                                disabled={loading !== null}
                            />
                            <Button
                                size="sm"
                                onClick={handleChat}
                                disabled={loading !== null || !chatInput.trim()}
                                className="h-10 w-10 p-0"
                            >
                                {loading === 'chat' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                            </Button>
                        </div>
                    </div>

                    {/* Evidence Canvas (compact compare) */}
                    <div className="mt-4 z-10">
                        <h3 className="font-bold uppercase tracking-widest text-xs flex items-center gap-2 text-foreground/80 mb-3">
                            <Database className="w-4 h-4" />
                            Evidence Canvas
                        </h3>
                        <div className="h-[200px] overflow-y-auto">
                            {models.length === 0 ? (
                                <div className="text-center py-8">
                                    <Activity className="w-8 h-8 text-muted-foreground/30 mx-auto animate-pulse" />
                                    <p className="text-xs uppercase tracking-widest font-bold text-muted-foreground/50 mt-2">Loading...</p>
                                </div>
                            ) : (
                                <ComparePage models={models} compact={true} />
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
