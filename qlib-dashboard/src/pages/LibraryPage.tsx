import { useEffect, useState } from 'react';
import { FolderArchive, HardDrive, History, LockKeyhole, RefreshCw } from 'lucide-react';
import { BundleOpenPanel } from '@/components/BundleOpenPanel';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { listRecentBundles, type RecentBundleRecord } from '@/lib/bundle-library';
import { useActiveResearchBundle } from '@/hooks/useActiveResearchBundle';

export function LibraryPage() {
  const active = useActiveResearchBundle();
  const [recent, setRecent] = useState<RecentBundleRecord[]>([]);

  const reload = () => void listRecentBundles().then(setRecent).catch(() => setRecent([]));
  useEffect(reload, []);

  return (
    <div className="research-page space-y-6">
      <header className="research-page-header">
        <div>
          <p className="research-kicker">Library / Research sources</p>
          <h1>Open and manage evidence bundles</h1>
          <p>Switch between published and local Alpha Engine results without uploading private research files.</p>
        </div>
        <Badge variant="outline" className="h-7 gap-1.5"><LockKeyhole className="h-3.5 w-3.5" /> Read only</Badge>
      </header>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.6fr)]">
        <Card className="research-surface">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base"><FolderArchive className="h-4 w-4 text-primary" /> Open research bundle</CardTitle>
          </CardHeader>
          <CardContent><BundleOpenPanel onOpened={reload} /></CardContent>
        </Card>

        <div className="space-y-5">
          <Card className="research-surface">
            <CardHeader><CardTitle className="flex items-center gap-2 text-sm"><HardDrive className="h-4 w-4 text-primary" /> Active source</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div>
                <p className="text-base font-semibold">{active?.manifest.title || 'Published bundle is loading'}</p>
                <p className="mt-1 text-xs text-muted-foreground">{active?.source.label || 'GitHub Pages bundle'}</p>
              </div>
              {active && (
                <dl className="grid grid-cols-2 gap-3 text-xs">
                  <div className="research-stat"><dt>Evidence cutoff</dt><dd>{active.manifest.evidence_cutoff || 'Not declared'}</dd></div>
                  <div className="research-stat"><dt>Models</dt><dd>{active.manifest.scope.model_count}</dd></div>
                  <div className="research-stat"><dt>Files</dt><dd>{active.manifest.artifacts.length}</dd></div>
                  <div className="research-stat"><dt>Integrity</dt><dd>{active.integrity === 'all_verified' ? 'Full' : 'Core'}</dd></div>
                </dl>
              )}
            </CardContent>
          </Card>

          <Card className="research-surface">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2 text-sm"><History className="h-4 w-4 text-primary" /> Recent sources</CardTitle>
              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={reload} aria-label="Refresh recent bundles"><RefreshCw className="h-3.5 w-3.5" /></Button>
            </CardHeader>
            <CardContent className="space-y-2">
              {recent.length === 0 ? (
                <p className="text-sm text-muted-foreground">No local bundle has been opened yet.</p>
              ) : recent.slice(0, 6).map((row) => (
                <div key={row.bundleId} className="rounded-lg border px-3 py-2">
                  <p className="truncate text-sm font-medium">{row.title}</p>
                  <p className="mt-1 text-[11px] text-muted-foreground">{row.sourceLabel} · {new Date(row.openedAt).toLocaleString()}</p>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
