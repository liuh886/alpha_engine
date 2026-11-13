import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, ArrowUpRight, ClipboardList, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAccessControl } from '@/hooks/useAccessControl';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { buildBriefEntries, summarizeBrief } from '@/lib/research-brief';
import { buildDailyResearchSummary } from '@/lib/research-summary';
import type { StrategyObservationBrief, StrategyOperationsSnapshot } from '@/lib/strategy-operations';

const WORKFLOWS = 'https://github.com/liuh886/alpha_engine/actions/workflows/';
const COPY_SUCCESS = 'Copied research summary to clipboard.';
const COPY_FAILURE = 'Copy failed. Clipboard unavailable — select the brief and copy manually.';
const REVIEW_NOT_VERIFIED = 'Review state not verified';

function copyWithTextarea(text: string): boolean {
  if (typeof document === 'undefined' || typeof document.execCommand !== 'function') return false;
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.readOnly = true;
  textarea.setAttribute('aria-hidden', 'true');
  textarea.style.position = 'fixed';
  textarea.style.top = '-1000px';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  try {
    textarea.select();
    textarea.setSelectionRange(0, text.length);
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    textarea.remove();
  }
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall back to the legacy selection path when the Clipboard API is rejected.
  }
  return copyWithTextarea(text);
}

/** An access-restricted brief never verified its cadence, so the page matches the copied summary there. */
function reviewLabel(brief: StrategyObservationBrief): string {
  if (brief.kind === 'access') return REVIEW_NOT_VERIFIED;
  return brief.recovery ? 'Action required' : 'Scheduled cadence';
}

export function DailyResearchBrief({ runs, snapshots, loading, reload }: {
  runs: GovernedRunSummary[];
  snapshots: Map<string, StrategyOperationsSnapshot>;
  loading: boolean;
  reload: () => void;
}) {
  const access = useAccessControl();
  const entries = buildBriefEntries(runs, snapshots, loading, access);
  const summary = summarizeBrief(entries, loading, Boolean(access.loading || access.policyLoading));
  const busy = summary.busy;
  const priorities = entries.slice(0, 3);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  useEffect(() => {
    if (copyState !== 'copied') return;
    const timer = window.setTimeout(() => setCopyState('idle'), 2000);
    return () => window.clearTimeout(timer);
  }, [copyState]);
  const copyBrief = async () => {
    try {
      const markdown = buildDailyResearchSummary(entries, { generatedAt: new Date() });
      setCopyState(await copyToClipboard(markdown) ? 'copied' : 'failed');
    } catch {
      setCopyState('failed');
    }
  };
  return (
    <section className="overflow-hidden rounded-2xl border bg-card shadow-sm" aria-label="Daily research brief" aria-busy={busy}>
      <header className="border-b bg-muted/15 px-5 py-3.5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold"><ClipboardList className="h-4 w-4 text-primary" />Daily research brief</h2>
          <div className="flex flex-col items-end gap-1">
            <Button variant="outline" size="sm" className="min-h-[44px]" onClick={() => { void copyBrief(); }}
              disabled={busy || !entries.length}>
              <Copy className="mr-2 h-4 w-4" aria-hidden="true" />Copy today's research summary
            </Button>
            <span role="status" aria-live="polite" className="max-w-[18rem] text-right text-xs text-muted-foreground">
              {copyState === 'copied' ? COPY_SUCCESS : copyState === 'failed' ? COPY_FAILURE : ''}
            </span>
          </div>
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">Latest verified observations by strategy. Each market keeps its own cutoff; retained targets are dated separately.</p>
        <p className="mt-1 text-xs" role="status">{busy ? 'Reading current observations…' : `${summary.changed} changed · ${summary.unchanged} unchanged · ${summary.retained} retained · ${summary.attention} need attention · ${summary.access} require access · ${summary.pending} awaiting verification`}</p>
        {summary.noNewChanges && <p className="mt-1 text-sm">No new model changes. Retained targets keep their recorded dates.</p>}
      </header>
      {!runs.length && <p className="p-5 text-sm text-muted-foreground">{busy ? 'Reading formal strategies…' : 'No formal strategies are available for this brief.'}</p>}
      {!busy && summary.access > 0 && (
        <div role="note" className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/20 px-5 py-2 text-xs">
          <p>
            <span className="font-semibold">{summary.access} {summary.access === 1 ? 'strategy requires' : 'strategies require'} protected access.</span>{' '}
            <span className="text-muted-foreground">Formal history stays readable; current observations remain hidden.</span>
          </p>
          <Button variant="outline" size="sm" className="min-h-[44px]" onClick={access.openAccount}>Check strategy access</Button>
        </div>
      )}
      <div className="divide-y">{priorities.map(({ run, snapshot, brief }) => (
        <article key={run.key} className="px-5 py-3" aria-label={`${run.title} daily observation`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Link to={`/strategies/${encodeURIComponent(run.modelVersionId)}`} className="text-sm font-semibold hover:text-primary">{run.title}</Link>
            <span className={brief.kind === 'attention' ? 'text-xs font-medium text-warning' : 'text-xs font-medium text-muted-foreground'}>{loading && !snapshot ? 'Checking observation' : brief.label}</span>
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">{run.market.toUpperCase()} · {snapshot
            ? `Observed ${snapshot.latestCompletedSession ?? 'unknown'} · target dated ${snapshot.decisionSchedule?.signalDate ?? snapshot.asOf ?? 'unknown'} · formal evidence ${run.evidenceCutoff}`
            : `Formal evidence ${run.evidenceCutoff}; current observation not verified`}</p>
          {snapshot?.decisionSchedule?.completedThrough && <p className="mt-0.5 text-[11px] text-muted-foreground">Completed market through {snapshot.decisionSchedule.completedThrough}</p>}
          <p className="mt-1.5 break-words text-sm">{brief.reason}</p>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{brief.nextStep}</p>
          {snapshot?.factorEvidence.length ? <details className="mt-1.5 text-xs">
            <summary className="cursor-pointer font-medium">Decision evidence</summary>
            <ul className="mt-2 space-y-1 text-muted-foreground">{snapshot.factorEvidence.slice(0, 3).map(factor => (
              <li key={`${factor.factorId}:${factor.factorVersion}`}>{factor.displayName}: {factor.state} · {factor.effect} · observed {factor.observedAt}</li>
            ))}</ul>
            <Link className="mt-2 inline-block text-primary underline" to={`/strategies/${encodeURIComponent(run.modelVersionId)}`}>Inspect all evidence</Link>
          </details> : null}
          {!busy && brief.recovery === 'read' && <Button variant="outline" size="sm" className="mt-2 min-h-[44px]" onClick={reload}>Retry reading observations</Button>}
          {brief.recovery && brief.recovery !== 'read' && <details className="mt-2 rounded-lg border bg-muted/15 p-3 text-xs">
            <summary className="cursor-pointer font-medium">Recovery steps</summary>
            <p className="mt-2 leading-relaxed text-muted-foreground">{brief.recovery === 'delivery'
              ? 'Review the delivery history. The existing outbox skips completed deliveries and retains ambiguous failures for review.'
              : 'Check model monitoring and the latest source run. When inputs are available, the existing refresh rechecks the frozen contract. Valid independent observations remain readable.'}</p>
            <div className="mt-3 flex flex-wrap gap-4">
              <Link className="text-primary underline" to="/system">Open operating status</Link>
              <a className="inline-flex items-center gap-1 text-primary underline" href={`${WORKFLOWS}${brief.recovery === 'delivery' ? 'strategy-signal-delivery-outbox.yml' : 'formal-backtest-refresh.yml'}`} target="_blank" rel="noreferrer">{brief.recovery === 'delivery' ? 'Open delivery workflow' : 'Open data refresh workflow'}<ArrowUpRight className="h-3 w-3" /></a>
            </div>
            <p className="mt-2 text-muted-foreground">An authorized operator can use Run workflow on main. This page reads records; it does not start jobs or send orders.</p>
          </details>}
          <div className="mt-2 flex items-center justify-between border-t pt-1.5">
            <span className="text-[11px] text-muted-foreground">
              Review: {reviewLabel(brief)}
            </span>
            <Link
              to={`/strategies/${encodeURIComponent(run.modelVersionId)}`}
              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              Inspect evidence <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
        </article>
      ))}</div>
    </section>
  );
}
