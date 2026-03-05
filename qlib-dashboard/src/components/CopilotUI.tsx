import React, { useState, useRef, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Send, Bot, User, BrainCircuit, Maximize2, Minimize2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from "@/lib/utils";

interface Message {
    role: 'user' | 'assistant' | 'system';
    content: string;
}

export function CopilotUI() {
    const [messages, setMessages] = useState<Message[]>([
        {
            role: 'system',
            content: 'Agentic Alpha Copilot initialized. I DO NOT execute trades directly. I analyze, score, and recommend. What sector should we investigate today?',
        }
    ]);
    const [input, setInput] = useState('');
    const [isTyping, setIsTyping] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);
    const [expanded, setExpanded] = useState(false);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages, isTyping, expanded]);

    const handleSend = async () => {
        if (!input.trim()) return;

        // Add User Message
        const userText = input;
        const userMsg: Message = { role: 'user', content: userText };
        setMessages(prev => [...prev, userMsg]);
        setInput('');
        setIsTyping(true);

        try {
            const resp = await fetch("/api/agent/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: userText, agent_type: "alpha" })
            });
            const data = await resp.json();

            const respMsg: Message = {
                role: 'assistant',
                content: data.ok ? data.reply : `**Error from AgentRouter:** ${data.error}`
            };
            setMessages(prev => [...prev, respMsg]);
        } catch (e) {
            setMessages(prev => [...prev, { role: 'assistant', content: "**Network Error**: Could not reach AgentRouter." }]);
        } finally {
            setIsTyping(false);
        }
    };

    return (
        <Card className={cn(
            "glass-panel transition-all duration-300 flex flex-col h-full",
            expanded ? "fixed inset-4 z-50 h-[calc(100vh-2rem)]" : "relative min-h-[500px] border-none shadow-none rounded-none bg-transparent backdrop-blur-none"
        )}>
            <CardHeader className="bg-primary/5 border-b pb-3 flex flex-row items-center justify-between">
                <div className="flex items-center gap-2">
                    <BrainCircuit className="w-5 h-5 text-primary" />
                    <CardTitle className="font-black text-sm uppercase tracking-widest text-primary">Alpha Copilot</CardTitle>
                </div>
                <Button variant="ghost" size="icon" onClick={() => setExpanded(!expanded)} className="h-8 w-8 hover:bg-primary/20 hover:text-primary transition-colors">
                    {expanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
                </Button>
            </CardHeader>

            <CardContent className="flex flex-col flex-1 p-0 overflow-hidden">
                {/* Chat Area */}
                <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4 pr-2 custom-scrollbar">
                    {messages.map((m, i) => (
                        <div key={i} className={cn("flex gap-3 max-w-[85%]", m.role === 'user' ? "ml-auto flex-row-reverse" : "")}>

                            {/* Avatar */}
                            <div className={cn(
                                "w-8 h-8 rounded-full flex items-center justify-center shrink-0 border",
                                m.role === 'user' ? "bg-primary text-primary-foreground border-primary/50" :
                                    m.role === 'system' ? "bg-muted border-border/50 text-muted-foreground" :
                                        "bg-blue-500/10 text-blue-500 border-blue-500/20"
                            )}>
                                {m.role === 'user' ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                            </div>

                            {/* Message Bubble */}
                            <div className={cn(
                                "rounded-2xl px-5 py-3.5 text-[13px] leading-relaxed relative group shadow-sm",
                                m.role === 'user' ? "bg-primary text-primary-foreground font-medium rounded-tr-sm" :
                                    m.role === 'system' ? "bg-muted/30 border border-white/5 backdrop-blur-sm text-muted-foreground rounded-tl-sm font-mono text-xs" :
                                        "bg-background/40 backdrop-blur-md border border-white/10 rounded-tl-sm text-foreground"
                            )}>
                                {m.role === 'user' ? (
                                    m.content
                                ) : (
                                    <div
                                        className="prose prose-sm dark:prose-invert max-w-none prose-p:leading-snug prose-li:my-0.5 prose-ul:my-2 prose-strong:text-primary"
                                    >
                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                            {m.content}
                                        </ReactMarkdown>
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}

                    {isTyping && (
                        <div className="flex gap-3 max-w-[85%] animate-in fade-in slide-in-from-bottom-2">
                            <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 border bg-blue-500/10 text-blue-500 border-blue-500/20">
                                <Bot className="w-4 h-4 animate-pulse" />
                            </div>
                            <div className="rounded-2xl px-4 py-3 bg-card border border-border/50 shadow-sm rounded-tl-sm flex items-center gap-1.5 h-[46px]">
                                <div className="w-1.5 h-1.5 rounded-full bg-blue-500/60 animate-bounce [animation-delay:-0.3s]" />
                                <div className="w-1.5 h-1.5 rounded-full bg-blue-500/60 animate-bounce [animation-delay:-0.15s]" />
                                <div className="w-1.5 h-1.5 rounded-full bg-blue-500/60 animate-bounce" />
                            </div>
                        </div>
                    )}
                </div>

                {/* Input Area */}
                <div className="p-3 border-t border-white/5 bg-background/20 backdrop-blur-md mt-auto rounded-b-xl">
                    <form
                        onSubmit={(e: React.FormEvent) => { e.preventDefault(); handleSend(); }}
                        className="flex items-center gap-2 relative"
                    >
                        <Input
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            placeholder="Ask the Copilot to analyze a specific pair..."
                            className="bg-background border-border/50 focus-visible:ring-primary pr-12 rounded-xl h-11 transition-all"
                        />
                        <Button
                            type="submit"
                            size="icon"
                            disabled={!input.trim() || isTyping}
                            className="absolute right-1 rounded-lg w-9 h-9 transition-transform active:scale-95"
                        >
                            <Send className="w-4 h-4 ml-0.5" />
                        </Button>
                    </form>
                    <div className="text-center mt-2">
                        <span className="text-[9px] uppercase tracking-widest text-muted-foreground font-black opacity-50">Copilot Answers are Non-Binding</span>
                    </div>
                </div>
            </CardContent>
        </Card>
    );
}
