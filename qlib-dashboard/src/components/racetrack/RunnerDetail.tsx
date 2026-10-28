import { useEffect, useRef, useState } from 'react';
import type { ProjectionClient, RaceEntry, RaceProjection, RunnerDetail as Detail } from '@/lib/racetrack-projection';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';

export const percent = (value: number | null, digits = 1) => value === null ? 'Unavailable' : `${(value * 100).toFixed(digits)}%`;

export function RunnerDetail({ projection, entry, client, onClose }: {
  projection: RaceProjection; entry: RaceEntry; client: ProjectionClient; onClose: () => void;
}) {
  const [result, setResult] = useState<{ id: string; detail?: Detail; error?: string } | null>(null);
  const origin = useRef(document.activeElement as HTMLElement | null);
  useEffect(() => {
    const controller = new AbortController(); setResult(null);
    void client.runner(projection, entry, controller.signal).then(
      detail => { if (!controller.signal.aborted) setResult({ id: entry.runner_id, detail }); },
      error => { if (!controller.signal.aborted) setResult({ id: entry.runner_id, error: error instanceof Error ? error.message : 'Runner detail could not be verified.' }); },
    );
    return () => controller.abort();
  }, [projection, entry.runner_id, entry.runner_version, client]);
  const current = result?.id === entry.runner_id ? result : null;
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-3xl [&>button:last-child]:hidden"
      onCloseAutoFocus={event => { event.preventDefault(); origin.current?.focus(); }}>
    <section className="min-w-0" aria-label="Runner detail">
    <header className="flex items-start justify-between gap-3 border-b pb-4">
      <div className="min-w-0"><p className="text-[10px] font-semibold uppercase tracking-[.2em] text-muted-foreground">Research runner</p>
        <DialogTitle className="mt-1 break-all text-lg font-semibold">{entry.runner_id}</DialogTitle>
        <DialogDescription className="mt-1 text-xs text-muted-foreground">Version {entry.runner_version} · model snapshot {projection.manifest.as_of_session}</DialogDescription>
      </div>
      <button onClick={onClose} className="min-h-9 rounded-md border px-3 text-xs" aria-label="Close runner detail">Close</button>
    </header>
    {!current && <p role="status" className="py-6 text-sm text-muted-foreground">Verifying runner detail…</p>}
    {current?.error && <div className="mt-4 space-y-3 text-sm"><p role="alert">{current.error}</p><h4 className="font-semibold">Published summary only</h4><p>{entry.thesis_summary || 'No thesis summary published.'}</p></div>}
    {current?.detail && <div className="mt-4 space-y-5 text-sm">
      <div><h4 className="font-semibold">Investment thesis</h4><p className="mt-2 whitespace-pre-wrap leading-relaxed text-muted-foreground">{current.detail.thesis}</p></div>
      <div><h4 className="font-semibold">Selection logic</h4><p className="mt-2 text-muted-foreground">{current.detail.selection_logic}</p></div>
      <div><h4 className="font-semibold">Rebalance logic</h4><p className="mt-2 text-muted-foreground">{current.detail.rebalance_logic}</p></div>
      <div><h4 className="font-semibold">Published risk and reference comparison</h4>
        <dl className="mt-3 grid grid-cols-2 gap-3 text-xs tabular-nums">
          <div><dt className="text-muted-foreground">Replay drawdown</dt><dd className="mt-1 font-medium">{percent(entry.max_drawdown)}</dd></div>
          <div><dt className="text-muted-foreground">Replay Sharpe</dt><dd className="mt-1 font-medium">{entry.sharpe_ratio.toFixed(2)}</dd></div>
          <div><dt className="text-muted-foreground">Excess vs {projection.manifest.benchmark_symbol === '000300' ? 'CSI 300' : projection.manifest.benchmark_symbol}</dt><dd className="mt-1 font-medium">{percent(entry.excess_vs_qqq)}</dd></div>
          <div><dt className="text-muted-foreground">Excess vs pool</dt><dd className="mt-1 font-medium">{percent(entry.excess_vs_pool)}</dd></div>
        </dl>
        <p className="mt-2 text-[11px] text-muted-foreground">Excess uses the publisher's 1Y period when available, otherwise the full replay; it does not follow the chart window.</p>
      </div>
      <div><h4 className="font-semibold">Hypothetical model weights</h4><p className="mt-1 text-xs text-muted-foreground">Replay cutoff allocations. These are not account holdings or live targets.</p>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-xs tabular-nums">
          {current.detail.model_weights.map(row => <div key={row.symbol} className="flex justify-between gap-2 rounded-md bg-muted/40 px-3 py-2"><dt>{row.symbol}</dt><dd>{percent(row.weight)}</dd></div>)}
          <div className="flex justify-between gap-2 rounded-md bg-muted/40 px-3 py-2"><dt>Cash</dt><dd>{percent(current.detail.cash_weight)}</dd></div>
        </dl>
      </div>
      <div><h4 className="font-semibold">Monthly rank history</h4><div className="mt-2 max-h-48 overflow-auto">
        <table className="w-full text-left text-xs tabular-nums"><thead><tr className="text-muted-foreground"><th className="py-2">Month</th><th>Rank</th><th>Points</th><th>Net return</th></tr></thead>
          <tbody>{current.detail.monthly_ranks.map(row => <tr key={row.month} className="border-t"><td className="py-2">{row.month}</td><td>{row.rank} / {row.total_runners}</td><td>{row.points_earned}</td><td>{percent(row.monthly_net_return)}</td></tr>)}</tbody>
        </table>
      </div></div>
      <p className="text-xs text-muted-foreground">Rebalance ledger and measured indicator associations: not published in this contract.</p>
      <ul className="space-y-2 border-t pt-4 text-xs leading-relaxed text-muted-foreground">{current.detail.limitations.map(line => <li key={line}>{line}</li>)}</ul>
    </div>}
  </section></DialogContent></Dialog>;
}
