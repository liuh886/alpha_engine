import type { RdiResearchBriefing } from '@/lib/rdi-research';

type Comparison = RdiResearchBriefing['historical_comparison'][number];
const percent = (value: number, digits = 1) => (value * 100).toFixed(digits) + '%';
const count = (value: number) => value.toLocaleString('en-US');

export function RdiHistoricalComparison({ rows, priceCutoff, horizon, onHorizonChange, exactValuesOpen, onExactValuesOpenChange }: {
  rows: Comparison[]; priceCutoff: string; horizon: number; onHorizonChange: (value: number) => void;
  exactValuesOpen: boolean; onExactValuesOpenChange: (value: boolean) => void;
}) {
  const selected = rows.find(row => row.horizon_sessions === horizon)!;
  const difference = (selected.drawdown_loss_frequency - selected.other_loss_frequency) * 100;
  return <div className="min-w-0 rounded-lg border bg-muted/15 p-4 sm:p-5">
    <h3 id="rdi-history-title" className="font-semibold">Historical price comparison</h3>
    <p className="mt-1 text-xs font-medium text-muted-foreground">Descriptive control · not an RDI forecast</p>
    <p className="mt-3 text-sm text-muted-foreground">Frequency of a CSI300 close-to-close loss of at least 5%. Compare prior 60-session drawdown ≥10% with other price states.</p>
    <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
      <span className="text-xs text-muted-foreground">Inspect a trading-session horizon</span>
      <div role="group" aria-label="Historical comparison horizon" className="inline-flex rounded-lg border bg-card p-1">
        {rows.map(row => <button key={row.horizon_sessions} type="button" aria-pressed={horizon === row.horizon_sessions}
          onClick={() => onHorizonChange(row.horizon_sessions)} className={'min-h-10 min-w-11 rounded-md px-3 text-sm font-medium ' + (horizon === row.horizon_sessions ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted')}>
          {row.horizon_sessions}<span className="sr-only"> trading sessions</span>
        </button>)}
      </div>
    </div>
    <figure className="mt-4" aria-labelledby="rdi-history-title">
      <div className="space-y-3">
        {rows.map(row => <div key={row.horizon_sessions} className={'rounded-md border p-3 ' + (horizon === row.horizon_sessions ? 'border-primary/35 bg-primary/5' : 'border-transparent')}>
          <p className="mb-2 text-xs font-semibold">{row.horizon_sessions} sessions</p>
          {([
            ['Prior drawdown ≥10%', row.drawdown_loss_frequency, true],
            ['Other price states', row.other_loss_frequency, false],
          ] as const).map(([name, value, focal]) => <div key={name} className="mt-2">
            <div className="mb-1 flex justify-between gap-3 text-[11px]"><span className="text-muted-foreground">{name}</span><span className="shrink-0 font-medium tabular-nums">{percent(value)}</span></div>
            <div role="meter" aria-label={`${row.horizon_sessions} sessions, ${name}, historical loss frequency`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Number((value * 100).toFixed(4))} aria-valuetext={percent(value, 2)} className="h-2 overflow-hidden rounded-sm bg-muted">
              <div className={'h-full rounded-sm ' + (focal ? 'bg-primary' : 'bg-slate-400 dark:bg-slate-500')} style={{ width: `${value * 100}%` }} />
            </div>
          </div>)}
        </div>)}
      </div>
      <figcaption className="mt-1 flex justify-between px-3 text-[10px] tabular-nums text-muted-foreground"><span>0%</span><span>50%</span><span>100% frequency</span></figcaption>
    </figure>
    <div role="group" aria-label={`${horizon}-session details`} aria-live="polite" className="mt-4 rounded-md border bg-card p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-1"><h4 className="text-sm font-semibold">{horizon}-session detail</h4><span className="text-xs text-muted-foreground">Historical frequency</span></div>
      <dl className="mt-3 grid grid-cols-2 gap-3 text-xs">
        <div><dt className="min-h-8 text-muted-foreground sm:min-h-0">Prior drawdown ≥10%</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{percent(selected.drawdown_loss_frequency, 2)}</dd><dd className="mt-1 text-muted-foreground">n={count(selected.drawdown_observations)}</dd></div>
        <div><dt className="min-h-8 text-muted-foreground sm:min-h-0">Other price states</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{percent(selected.other_loss_frequency, 2)}</dd><dd className="mt-1 text-muted-foreground">n={count(selected.other_observations)}</dd></div>
      </dl>
      <p className="mt-3 text-xs text-muted-foreground">Latest mature observation {selected.latest_mature_observation}; labels through {selected.latest_label_end}. {selected.immature_observations} later observations await complete future sessions.</p>
      <p className="mt-3 border-t pt-2 text-xs text-muted-foreground">Frequency difference <span className="font-semibold tabular-nums text-foreground">{difference > 0 ? '+' : ''}{difference.toFixed(2)} pp</span> <span className="whitespace-nowrap">(percentage points)</span></p>
    </div>
    <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">Prices end {priceCutoff}. Overlapping observations are not independent samples. This is not a current loss probability, calibrated RDI forecast or tradable return.</p>
    <details open={exactValuesOpen} className="mt-3 border-t pt-2">
      {/* Own activation synchronously: queued native toggle events must not overwrite a restored view. */}
      <summary onClick={event => { event.preventDefault(); onExactValuesOpenChange(!exactValuesOpen); }} className="min-h-10 cursor-pointer py-2 text-xs font-medium">View exact historical values</summary>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <caption className="sr-only">Descriptive price-only severe-loss frequencies and overlapping sample counts</caption>
          <thead><tr className="border-b text-muted-foreground"><th className="py-2 pr-2">Horizon</th><th className="p-2">Prior drawdown ≥10%</th><th className="py-2 pl-2">Other states</th></tr></thead>
          <tbody>{rows.map(row => <tr key={row.horizon_sessions} className="border-b last:border-0">
            <th scope="row" className="py-2 pr-2 font-medium">{row.horizon_sessions} sessions</th>
            <td className="p-2 tabular-nums">{percent(row.drawdown_loss_frequency, 2)}<span className="mt-1 block text-muted-foreground">n={count(row.drawdown_observations)}</span></td>
            <td className="py-2 pl-2 tabular-nums">{percent(row.other_loss_frequency, 2)}<span className="mt-1 block text-muted-foreground">n={count(row.other_observations)}</span></td>
          </tr>)}</tbody>
        </table>
      </div>
    </details>
  </div>;
}
