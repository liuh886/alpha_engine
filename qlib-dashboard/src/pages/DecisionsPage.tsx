import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, CircleSlash2, FileQuestion, Loader2, ShieldCheck } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import { formatEvidenceLabel } from '@/lib/format-evidence-label';
import {
  loadDecisionForRun,
  type DecisionLoadState,
  type ResearchDecisionClaim,
  type ResearchDecisionReceipt,
} from '@/lib/model-run-decision';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

function ClaimGroup({ title, claims }: { title: string; claims: ResearchDecisionClaim[] }) {
  if (!claims.length) return null;
  return (
    <section className="rounded-xl border bg-card p-5 shadow-sm">
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="mt-3 space-y-3">
        {claims.map((claim) => (
          <article key={claim.claim_id} className="rounded-lg border bg-muted/20 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-mono text-xs font-semibold">{claim.claim_id}</span>
              <span className="rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase">{claim.outcome}</span>
            </div>
            <p className="mt-2 text-sm">{claim.statement}</p>
            <p className="mt-2 break-all text-[11px] text-muted-foreground">{claim.source_path} · {claim.source_sha256}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function DecisionReceipt({ decision }: { decision: ResearchDecisionReceipt }) {
  const VerdictIcon = decision.verdict === 'supported'
    ? CheckCircle2
    : decision.verdict === 'not_supported'
      ? AlertTriangle
      : CircleSlash2;
  return (
    <div className="space-y-5">
      <section className="rounded-xl border bg-card p-6 shadow-sm">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="flex items-start gap-3">
            <VerdictIcon className="mt-0.5 h-6 w-6 text-primary" />
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Verified research verdict</p>
              <h3 className="mt-1 text-2xl font-semibold">{formatEvidenceLabel(decision.verdict)}</h3>
              <p className="mt-2 text-sm text-muted-foreground">Status: {formatEvidenceLabel(decision.status)} · Receipt is bound to bundle {decision.bundle_id}.</p>
            </div>
          </div>
          <span className="rounded-full border px-3 py-1 text-xs font-semibold">Research only · not trade ready</span>
        </div>
      </section>

      <ClaimGroup title="Decision gates" claims={decision.gates} />
      <ClaimGroup title="Supporting evidence" claims={decision.supporting_evidence} />
      <ClaimGroup title="Contradictory evidence" claims={decision.contradictory_evidence} />

      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-xl border bg-card p-5 shadow-sm">
          <h3 className="text-sm font-semibold">Interpretation limits</h3>
          {decision.interpretation_limits.length
            ? <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-muted-foreground">{decision.interpretation_limits.map((row) => <li key={row}>{row}</li>)}</ul>
            : <p className="mt-3 text-sm text-muted-foreground">No additional limits were declared.</p>}
        </section>
        <section className="rounded-xl border bg-card p-5 shadow-sm">
          <h3 className="text-sm font-semibold">Failure modes</h3>
          {decision.failure_modes.length
            ? <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-muted-foreground">{decision.failure_modes.map((row) => <li key={row}>{row}</li>)}</ul>
            : <p className="mt-3 text-sm text-muted-foreground">No additional failure modes were declared.</p>}
        </section>
      </div>

      <section className="rounded-xl border border-primary/30 bg-primary/5 p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">One next permitted validation</p>
        <p className="mt-2 text-sm font-medium">{decision.next_permitted_validation_step}</p>
      </section>
    </div>
  );
}

export function DecisionsPage() {
  const { activeRun } = useOutletContext<RunWorkspaceContext>();
  const [state, setState] = useState<DecisionLoadState | { state: 'loading'; decision: null; error: null }>({
    state: 'loading',
    decision: null,
    error: null,
  });

  useEffect(() => {
    let active = true;
    if (!activeRun) {
      setState({ state: 'absent', decision: null, error: null });
      return () => { active = false; };
    }
    setState({ state: 'loading', decision: null, error: null });
    void loadDecisionForRun(activeRun).then((next) => {
      if (active) setState(next);
    });
    return () => { active = false; };
  }, [activeRun]);

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <section className="rounded-xl border bg-card p-6 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="rounded-lg bg-primary/10 p-3 text-primary"><ShieldCheck className="h-6 w-6" /></div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Governed decision boundary</p>
            <h2 className="mt-1 text-2xl font-semibold">Decisions</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              This workspace renders only companion receipts whose bytes, bundle identity and evidence references pass validation. The browser never infers or strengthens a verdict from charts or metrics.
            </p>
          </div>
        </div>
      </section>

      {state.state === 'loading' && (
        <div className="flex min-h-52 items-center justify-center rounded-xl border"><Loader2 className="mr-2 h-5 w-5 animate-spin" />Loading decision companion…</div>
      )}

      {state.state === 'error' && (
        <section className="rounded-xl border border-red-500/30 bg-red-500/5 p-8 text-center">
          <AlertTriangle className="mx-auto h-8 w-8 text-red-500" />
          <h3 className="mt-3 text-lg font-semibold">Decision receipt failed verification</h3>
          <p className="mx-auto mt-2 max-w-2xl text-sm text-muted-foreground">{state.error}</p>
          <p className="mt-3 text-xs font-semibold">No verdict is displayed.</p>
        </section>
      )}

      {state.state === 'absent' && (
        <section className="rounded-xl border-2 border-dashed p-10 text-center">
          <FileQuestion className="mx-auto h-9 w-9 text-muted-foreground" />
          <h3 className="mt-4 text-lg font-semibold">No decision receipt</h3>
          <p className="mx-auto mt-2 max-w-2xl text-sm text-muted-foreground">
            {activeRun
              ? `${activeRun.title} has no manifest-bound companion receipt. Absence remains explicit and does not imply support or rejection.`
              : 'Select a governed run. Absent and pending receipts remain explicit rather than being replaced by browser heuristics.'}
          </p>
        </section>
      )}

      {(state.state === 'pending' || state.state === 'completed') && state.decision && (
        <DecisionReceipt decision={state.decision} />
      )}
    </div>
  );
}
