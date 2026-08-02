import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AlertCircle, FileCode2, Loader2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { assetUrl } from '@/lib/runtime-capabilities';

function slugify(text: string): string {
  return String(text || '')
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-');
}

export function MethodologyPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [content, setContent] = useState('');
  const staticPath = 'docs/methodology.md';

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(assetUrl(staticPath), { cache: 'no-store' });
      if (!response.ok) {
        setError(`Failed to load exported methodology: HTTP ${response.status}`);
        return;
      }
      const text = await response.text();
      if (!text.trim()) {
        setError('Methodology document is empty.');
        return;
      }
      setContent(text);
    } catch {
      setError('Failed to load methodology from the exported research site.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const headings = useMemo(() => {
    return content
      .split('\n')
      .filter((line) => /^#{1,3}\s+/.test(line))
      .map((line) => {
        const level = line.match(/^#+/)?.[0].length || 1;
        const title = line.replace(/^#+\s+/, '').trim();
        return { level, title, id: slugify(title) };
      });
  }, [content]);

  if (loading) {
    return <div className="flex min-h-72 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary/60" /></div>;
  }

  if (error) {
    return (
      <div className="research-empty-state">
        <AlertCircle className="mx-auto h-8 w-8 text-amber-500" />
        <h2 className="mt-4 text-lg font-semibold">Methodology unavailable</h2>
        <p className="mt-2 text-sm text-muted-foreground">{error}</p>
        <Button variant="outline" className="mt-5 gap-2" onClick={() => void load()}>
          <RefreshCw className="h-4 w-4" /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto grid max-w-[1400px] gap-6 pb-16 lg:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="hidden lg:block">
        <div className="sticky top-28 rounded-xl border bg-card p-4">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground">On this page</p>
          <nav className="mt-3 space-y-1" aria-label="Methodology contents">
            {headings.filter((heading) => heading.level <= 2).map((heading) => (
              <a
                key={heading.id}
                href={`#${heading.id}`}
                className={cn('block rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground', heading.level === 2 && 'pl-4')}
              >
                {heading.title}
              </a>
            ))}
          </nav>
        </div>
      </aside>

      <Card>
        <CardHeader className="border-b">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-primary">Research contract</p>
              <CardTitle className="mt-2 text-2xl">Methodology and interpretation boundaries</CardTitle>
              <p className="mt-2 text-sm text-muted-foreground">This document is bundled at site build time and does not depend on a local server.</p>
            </div>
            <div className="flex items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              <FileCode2 className="h-4 w-4" /> {staticPath}
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-6 md:p-9">
          <article className="prose prose-slate max-w-none dark:prose-invert prose-headings:scroll-mt-32">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({ children }) => <h1 id={slugify(String(children))}>{children}</h1>,
                h2: ({ children }) => <h2 id={slugify(String(children))}>{children}</h2>,
                h3: ({ children }) => <h3 id={slugify(String(children))}>{children}</h3>,
              }}
            >
              {content}
            </ReactMarkdown>
          </article>
        </CardContent>
      </Card>
    </div>
  );
}
