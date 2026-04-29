import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BookOpen, RefreshCw, AlertCircle, FileCode2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

type DocResponse = {
  ok: boolean;
  path?: string;
  content?: string;
  updated_at?: number;
};

type ReaderRole = "all" | "user" | "developer";

function slugify(text: string): string {
  return String(text || "")
    .toLowerCase()
    .trim()
    .replace(/[^\w\u4e00-\u9fa5\s-]/g, "")
    .replace(/\s+/g, "-");
}

function nodeText(children: ReactNode): string {
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map((x) => nodeText(x)).join("");
  if (children && typeof children === "object" && "props" in (children as any)) {
    return nodeText((children as any).props?.children);
  }
  return "";
}

function splitSections(md: string): { preface: string; sections: Array<{ title: string; body: string }> } {
  const lines = String(md || "").split(/\r?\n/);
  const sections: Array<{ title: string; body: string }> = [];
  const preface: string[] = [];

  let curTitle = "";
  let curBody: string[] = [];
  let inSection = false;

  for (const line of lines) {
    if (line.startsWith("## ")) {
      if (inSection) sections.push({ title: curTitle, body: curBody.join("\n").trim() });
      curTitle = line.replace(/^##\s+/, "").trim();
      curBody = [line];
      inSection = true;
      continue;
    }
    if (inSection) curBody.push(line);
    else preface.push(line);
  }
  if (inSection) sections.push({ title: curTitle, body: curBody.join("\n").trim() });
  return { preface: preface.join("\n").trim(), sections };
}

function composeRoleMarkdown(md: string, role: ReaderRole): string {
  if (role === "all") return md;
  const parsed = splitSections(md);
  const allowUser = [
    "1. Scope and Boundaries",
    "5. Configuration Guide",
    "6. WebUI Functional Map (User-facing)",
    "7. API Reference (Operational)",
    "10. Developer Workflows",
    "11. Troubleshooting",
  ];
  const allowDev = [
    "3. Architecture Overview",
    "4. Business Logic by Domain",
    "5. Configuration Guide",
    "7. API Reference (Operational)",
    "8. Implementation Deep Dive",
    "9. Security and Safety Notes",
    "10. Developer Workflows",
    "12. Known Gaps and Technical Debt",
    "13. Source Index (for traceability)",
    "14. PM Quality Gate (LifeOS-Soul)",
  ];
  const allow = role === "user" ? allowUser : allowDev;
  const picked = parsed.sections.filter((s) => allow.includes(s.title));
  const roleHeader = role === "user" ? "## Reader Mode: User\n" : "## Reader Mode: Developer\n";
  return [parsed.preface, roleHeader, ...picked.map((s) => s.body)].filter(Boolean).join("\n\n");
}

export function DocsPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [docPath, setDocPath] = useState("");
  const [docMd, setDocMd] = useState("");
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [role, setRole] = useState<ReaderRole>("all");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await fetch("/api/system/docs/main", { cache: "no-store" });
      if (!resp.ok) {
        setError(`Failed to load documentation: HTTP ${resp.status}`);
        return;
      }
      const json = (await resp.json()) as DocResponse;
      if (!json?.ok || !json?.content) {
        setError("Documentation payload is empty.");
        return;
      }
      setDocPath(String(json.path || ""));
      setDocMd(String(json.content || ""));
      setUpdatedAt(typeof json.updated_at === "number" ? json.updated_at : null);
    } catch (e) {
      setError("Failed to load documentation from API.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const updatedText = useMemo(() => {
    if (!updatedAt) return "N/A";
    return new Date(updatedAt * 1000).toLocaleString();
  }, [updatedAt]);

  const renderedMd = useMemo(() => composeRoleMarkdown(docMd, role), [docMd, role]);
  const toc = useMemo(() => {
    return renderedMd
      .split(/\r?\n/)
      .filter((line) => line.startsWith("## "))
      .map((line) => {
        const text = line.replace(/^##\s+/, "").trim();
        return { text, id: slugify(text) };
      });
  }, [renderedMd]);

  return (
    <div className="space-y-6 max-w-[1200px] mx-auto pb-16 text-left">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b pb-6">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-primary font-bold text-xs uppercase tracking-widest mb-1">
            <BookOpen className="h-3.5 w-3.5" /> User + Developer Handbook
          </div>
          <h1 className="text-4xl font-black tracking-tight">System Documentation</h1>
          <p className="text-muted-foreground text-sm max-w-2xl">
            Runtime architecture, business logic, configuration, API contracts, and implementation details.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="bg-muted p-1 rounded-lg flex gap-1 border">
            {(["all", "user", "developer"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setRole(m)}
                className={cn(
                  "px-3 py-1 text-[10px] uppercase font-black rounded-md transition-all",
                  role === m ? "bg-background shadow-sm text-primary" : "text-muted-foreground hover:text-foreground"
                )}
              >
                {m}
              </button>
            ))}
          </div>
          <Button onClick={load} disabled={loading} variant="outline" size="sm" className="h-9 gap-2 font-bold uppercase text-[10px]">
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /> Refresh
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <Card className="lg:col-span-1 border border-border/60 bg-card/60">
          <CardHeader>
            <CardTitle className="text-[10px] uppercase tracking-widest font-black flex items-center gap-2">
              <FileCode2 className="h-4 w-4" /> Source
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-xs">
            <div>
              <p className="text-muted-foreground uppercase text-[10px] font-bold">Document Path</p>
              <p className="font-mono break-all">{docPath || "N/A"}</p>
            </div>
            <div>
              <p className="text-muted-foreground uppercase text-[10px] font-bold">Last Updated</p>
              <p className="font-mono">{updatedText}</p>
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              The page renders a single markdown source from backend API to avoid documentation drift.
            </p>
            <div className="pt-2 border-t border-border/60">
              <p className="text-muted-foreground uppercase text-[10px] font-bold mb-2">Contents</p>
              <div className="space-y-1 max-h-[360px] overflow-auto pr-1">
                {toc.map((x) => (
                  <a key={x.id} href={`#${x.id}`} className="block text-[11px] hover:text-primary transition-colors">
                    {x.text}
                  </a>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="lg:col-span-4 border border-border/60 bg-card/60">
          <CardContent className="pt-6">
            {error ? (
              <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-400 flex gap-2">
                <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            ) : (
              <article className="prose prose-invert max-w-none prose-headings:tracking-tight prose-h1:text-3xl prose-h2:text-xl prose-h3:text-base prose-p:text-sm prose-li:text-sm prose-table:text-xs">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    h1: ({ children }) => {
                      const text = nodeText(children);
                      return <h1 id={slugify(text)}>{children}</h1>;
                    },
                    h2: ({ children }) => {
                      const text = nodeText(children);
                      return <h2 id={slugify(text)}>{children}</h2>;
                    },
                    h3: ({ children }) => {
                      const text = nodeText(children);
                      return <h3 id={slugify(text)}>{children}</h3>;
                    },
                  }}
                >
                  {renderedMd || "Loading documentation..."}
                </ReactMarkdown>
              </article>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
