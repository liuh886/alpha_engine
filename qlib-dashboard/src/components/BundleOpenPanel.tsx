import { useEffect, useRef, useState } from 'react';
import { Archive, CheckCircle2, FolderOpen, History, Loader2, ShieldCheck, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  DirectoryBundleSource,
  FileSetBundleSource,
  ZipBundleSource,
  openResearchBundle,
  setActiveResearchBundle,
  type DirectoryHandleLike,
  type OpenedResearchBundle,
} from '@/lib/research-bundle';
import { listRecentBundles, rememberBundle, type RecentBundleRecord } from '@/lib/bundle-library';

type PickerWindow = Window & {
  showDirectoryPicker?: (options?: { mode?: 'read' }) => Promise<DirectoryHandleLike>;
};

export function BundleOpenPanel({ onOpened }: { onOpened?: (bundle: OpenedResearchBundle) => void }) {
  const directoryInput = useRef<HTMLInputElement>(null);
  const zipInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [verifyAll, setVerifyAll] = useState(false);
  const [error, setError] = useState('');
  const [opened, setOpened] = useState<OpenedResearchBundle | null>(null);
  const [recent, setRecent] = useState<RecentBundleRecord[]>([]);

  useEffect(() => {
    directoryInput.current?.setAttribute('webkitdirectory', '');
    void listRecentBundles().then(setRecent).catch(() => setRecent([]));
  }, []);

  const activate = async (source: DirectoryBundleSource | FileSetBundleSource | ZipBundleSource, handle?: DirectoryHandleLike) => {
    setBusy(true);
    setError('');
    try {
      const bundle = await openResearchBundle(source, { verifyAll });
      setActiveResearchBundle(bundle);
      setOpened(bundle);
      onOpened?.(bundle);
      await rememberBundle(bundle.manifest, source.label, handle).catch(() => undefined);
      setRecent(await listRecentBundles().catch(() => []));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const openDirectory = async () => {
    const picker = (window as PickerWindow).showDirectoryPicker;
    if (!picker) {
      directoryInput.current?.click();
      return;
    }
    try {
      const handle = await picker({ mode: 'read' });
      const permission = handle.requestPermission ? await handle.requestPermission({ mode: 'read' }) : 'granted';
      if (permission !== 'granted') throw new Error('Read permission was not granted.');
      await activate(new DirectoryBundleSource(handle), handle);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') return;
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const reconnect = async (row: RecentBundleRecord) => {
    if (!row.directoryHandle) {
      setError('This recent bundle must be selected again because no reusable directory permission is available.');
      return;
    }
    const permission = row.directoryHandle.queryPermission
      ? await row.directoryHandle.queryPermission({ mode: 'read' })
      : 'prompt';
    if (permission !== 'granted' && row.directoryHandle.requestPermission) {
      const next = await row.directoryHandle.requestPermission({ mode: 'read' });
      if (next !== 'granted') {
        setError('Directory permission expired and was not renewed.');
        return;
      }
    }
    await activate(new DirectoryBundleSource(row.directoryHandle), row.directoryHandle);
  };

  return (
    <div className="space-y-4">
      <input
        ref={directoryInput}
        type="file"
        multiple
        className="hidden"
        onChange={(event) => {
          const files = event.target.files;
          if (files?.length) void activate(new FileSetBundleSource(Array.from(files)));
          event.target.value = '';
        }}
      />
      <input
        ref={zipInput}
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void ZipBundleSource.fromFile(file).then((source) => activate(source)).catch((cause) => setError(String(cause)));
          event.target.value = '';
        }}
      />

      <div className="flex flex-wrap gap-2">
        <Button onClick={openDirectory} disabled={busy} className="gap-2">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderOpen className="h-4 w-4" />}
          Open results folder
        </Button>
        <Button onClick={() => directoryInput.current?.click()} disabled={busy} variant="outline" className="gap-2">
          <Upload className="h-4 w-4" /> Select folder files
        </Button>
        <Button onClick={() => zipInput.current?.click()} disabled={busy} variant="outline" className="gap-2">
          <Archive className="h-4 w-4" /> Open ZIP
        </Button>
      </div>

      <label className="flex items-center gap-2 text-xs text-muted-foreground">
        <input type="checkbox" checked={verifyAll} onChange={(event) => setVerifyAll(event.target.checked)} />
        Verify every declared file now. Required indexes are always verified; large files otherwise verify when opened.
      </label>

      {opened && (
        <div className="rounded-lg border border-green-500/30 bg-green-500/5 p-3 text-sm">
          <div className="flex items-center gap-2 font-semibold text-green-700 dark:text-green-400">
            <CheckCircle2 className="h-4 w-4" /> {opened.manifest.title}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {opened.source.label} · cutoff {opened.manifest.evidence_cutoff || 'not declared'} · {opened.integrity.replace('_', ' ')}
          </div>
        </div>
      )}

      {error && <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}

      {recent.length > 0 && (
        <div className="rounded-lg border p-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <History className="h-3.5 w-3.5" /> Recent bundles
          </div>
          <div className="space-y-2">
            {recent.slice(0, 4).map((row) => (
              <button
                key={row.bundleId}
                type="button"
                onClick={() => void reconnect(row)}
                className="w-full rounded-md border bg-background px-3 py-2 text-left hover:border-primary/40 transition-colors"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium truncate">{row.title}</span>
                  <Badge variant="outline" className="text-[9px]">{row.directoryHandle ? 'Reconnect' : 'Reselect'}</Badge>
                </div>
                <div className="mt-1 text-[11px] text-muted-foreground">{row.sourceLabel} · opened {new Date(row.openedAt).toLocaleString()}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex gap-2 rounded-lg bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">
        <ShieldCheck className="h-4 w-4 shrink-0 text-primary" />
        Files are read inside this browser. GitHub Pages does not receive the selected contents, and no account or cloud synchronization is used.
      </div>
    </div>
  );
}
