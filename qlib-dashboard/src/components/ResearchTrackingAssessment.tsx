import type { DecisionLoadState, ResearchDecisionClaim } from '@/lib/model-run-decision';

function Claims({ title, claims }: { title: string; claims: ResearchDecisionClaim[] }) {
  return <div className="min-w-0">
    <h3 className="font-semibold">{title}</h3>
    {claims.length ? <ul className="mt-2 space-y-3 text-muted-foreground">
      {claims.map(row => <li key={row.claim_id} className="break-words">
        <span className="text-xs font-semibold uppercase">{row.outcome}</span> · {row.statement}
      </li>)}
    </ul> : <p className="mt-2 text-muted-foreground">No records in this assessment.</p>}
  </div>;
}

export function ResearchTrackingAssessment({ state, evidenceCutoff, primaryCounterevidence }: {
  state: DecisionLoadState | null;
  evidenceCutoff?: string | null;
  primaryCounterevidence?: string;
}) {
  const decision = state?.decision;
  return <section aria-label="Research tracking assessment" className="min-w-0 rounded-xl border bg-card p-5 text-sm">
    <h2 className="font-semibold">Research tracking assessment</h2>
    <p className="mt-2 text-muted-foreground">
      {decision
        ? decision.status === 'pending_review' ? 'Continuing effectiveness awaits review. Formal acceptance does not establish validation.' : `Reviewed research result: ${decision.verdict.replace(/_/g, ' ')}`
        : state?.state === 'error' ? 'Assessment evidence could not be verified.' : state?.state === 'absent' ? 'No assessment is bound to this evidence bundle.' : 'Loading verified assessment…'}
    </p>
    <p className="mt-2 text-xs text-muted-foreground">Research only. This assessment does not establish a trading instruction.</p>
    {decision && <>
      <p className="mt-2 break-words text-muted-foreground">{primaryCounterevidence || 'Retained evidence has no recorded counterevidence; this does not establish continued effectiveness.'}</p>
      <p className="mt-2 text-muted-foreground">{decision.gates.filter(row => row.outcome === 'failed').length} retained failed gates · {decision.contradictory_evidence.length} counterevidence records. Evidence through {evidenceCutoff || 'unknown'}.</p>
      <details className="mt-3">
        <summary className="cursor-pointer font-medium">Supporting evidence, counterevidence, limits and next validation</summary>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <Claims title="Supporting evidence" claims={decision.supporting_evidence} />
          <Claims title="Gates" claims={decision.gates} />
          <Claims title="Counterevidence" claims={decision.contradictory_evidence} />
          <div className="min-w-0">
            <h3 className="font-semibold">Interpretation limits</h3>
            {decision.interpretation_limits.length ? <ul className="mt-2 list-disc space-y-2 break-words pl-5 text-muted-foreground">
              {decision.interpretation_limits.map((limit, index) => <li key={index}>{limit}</li>)}
            </ul> : <p className="mt-2 text-muted-foreground">No interpretation limits recorded; this does not establish unrestricted applicability.</p>}
            {decision.failure_modes.length > 0 && <>
              <h3 className="mt-4 font-semibold">Recorded failure modes</h3>
              <ul className="mt-2 list-disc space-y-2 break-words pl-5 text-muted-foreground">{decision.failure_modes.map((mode, index) => <li key={index}>{mode}</li>)}</ul>
            </>}
          </div>
        </div>
        <h3 className="mt-5 font-semibold">Next permitted validation</h3>
        <p className="mt-2 break-words text-muted-foreground">{decision.next_permitted_validation_step}</p>
      </details>
    </>}
  </section>;
}
