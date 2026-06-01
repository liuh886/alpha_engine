import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2, AlertCircle, FileCode2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type DocResponse = {
  ok: boolean;
  path?: string;
  content?: string;
  updated_at?: number;
};

function slugify(text: string): string {
  return String(text || "")
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-");
}

export function MethodologyPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [content, setContent] = useState("");
  const [docPath, setDocPath] = useState("");
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await fetch("/api/system/docs/methodology", { cache: "no-store" });
      if (!resp.ok) {
        setError(`Failed to load: HTTP ${resp.status}`);
        return;
      }
      const json = (await resp.json()) as DocResponse;
      if (!json?.ok || !json?.content) {
        setError("Methodology document is empty.");
        return;
      }
      setContent(json.content);
      setDocPath(json.path || "");
      setUpdatedAt(typeof json.updated_at === "number" ? json.updated_at : null);
    } catch {
      setError("Failed to load methodology from API.");
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

  const toc = useMemo(() => {
    return content
      .split(/\r?\n/)
      .filter((line) => line.startsWith("## ") || line.startsWith("### "))
      .map((line) => {
        const level = line.startsWith("### ") ? 3 : 2;
        const text = line.replace(/^#{2,3}\s+/, "").trim();
        return { text, id: slugify(text), level };
      });
  }, [content]);

  if (loading) {
    return (
      <div className="h-96 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary opacity-40" />
      </div>
    );
  }

  return (
    <div className="max-w-[1200px] mx-auto pb-20 text-left">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-3 border-b pb-4 mb-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Training Methodology</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Complete reference for model training, evaluation, and risk controls.
          </p>
        </div>
        <Button onClick={load} disabled={loading} variant="outline" size="sm" className="h-8 gap-1.5 text-xs">
          <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} /> Refresh
        </Button>
      </div>

      {error ? (
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-400 flex gap-2">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* TOC */}
          <Card className="lg:col-span-1 border border-border/60 bg-card/60 sticky top-20 self-start">
            <CardHeader>
              <CardTitle className="text-[10px] uppercase tracking-widest font-black flex items-center gap-2">
                <FileCode2 className="h-4 w-4" /> Contents
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 max-h-[60vh] overflow-auto pr-1">
              {toc.map((x) => (
                <a
                  key={x.id}
                  href={`#${x.id}`}
                  className={cn(
                    "block text-[11px] hover:text-primary transition-colors",
                    x.level === 3 ? "pl-3" : "",
                    "font-medium"
                  )}
                >
                  {x.text}
                </a>
              ))}
              <div className="pt-3 border-t border-border/60 mt-3">
                <p className="text-muted-foreground uppercase text-[9px] font-bold">Source</p>
                <p className="font-mono text-[10px] break-all">{docPath}</p>
                <p className="text-muted-foreground uppercase text-[9px] font-bold mt-2">Updated</p>
                <p className="font-mono text-[10px]">{updatedText}</p>
              </div>
            </CardContent>
          </Card>

          {/* Content */}
          <Card className="lg:col-span-4 border border-border/60 bg-card/60">
            <CardContent className="p-8">
              <article className="prose prose-sm dark:prose-invert max-w-none
                prose-headings:font-black prose-headings:tracking-tight
                prose-h1:text-3xl prose-h1:border-b prose-h1:pb-4
                prose-h2:text-xl prose-h2:mt-10 prose-h2:border-b prose-h2:pb-2
                prose-h3:text-base
                prose-table:text-xs prose-table:font-mono
                prose-th:font-black prose-th:uppercase prose-th:text-[10px] prose-th:tracking-widest
                prose-td:py-2
                prose-code:text-xs prose-code:bg-muted prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded
                prose-pre:bg-muted prose-pre:text-xs
                prose-hr:border-border/50
              ">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    h1: ({ children }) => {
                      const text = typeof children === "string" ? children : "";
                      return <h1 id={slugify(text)}>{children}</h1>;
                    },
                    h2: ({ children }) => {
                      const text = typeof children === "string" ? children : "";
                      return <h2 id={slugify(text)}>{children}</h2>;
                    },
                    h3: ({ children }) => {
                      const text = typeof children === "string" ? children : "";
                      return <h3 id={slugify(text)}>{children}</h3>;
                    },
                  }}
                >
                  {content}
                </ReactMarkdown>
              </article>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
