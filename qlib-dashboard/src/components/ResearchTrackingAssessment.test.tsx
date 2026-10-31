import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { DecisionLoadState, ResearchDecisionReceipt } from '@/lib/model-run-decision';
import { parseResearchDecision } from '@/lib/model-run-decision';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { ResearchTrackingAssessment } from './ResearchTrackingAssessment';

const claim = { claim_id: 'support', outcome: 'passed' as const, statement: 'Retained source coverage passed.', source_path: 'evidence/source.json', source_sha256: 'a'.repeat(64) };
const decision: ResearchDecisionReceipt = {
  schema_version: '2.0.0', run_id: 'run', bundle_id: 'bundle', verdict: 'not_supported', status: 'completed',
  gates: [
    { ...claim, claim_id: 'gate', outcome: 'failed', statement: 'Stress acceptance failed.' },
    { ...claim, claim_id: 'review', outcome: 'blocked', statement: 'Independent review missing.' },
  ],
  supporting_evidence: [claim], contradictory_evidence: [{ ...claim, claim_id: 'counter', outcome: 'failed', statement: 'Stress result failed.' }],
  interpretation_limits: ['Historical evidence cannot establish future returns.'], failure_modes: ['Sparse observations.'],
  next_permitted_validation_step: 'Collect the next frozen observation.', research_only: true, trade_ready: false,
};

function verified(receipt: ResearchDecisionReceipt): ResearchDecisionReceipt {
  return parseResearchDecision(receipt, {
    runId: 'run', bundleId: 'bundle',
    manifest: { sections: [{ availability_status: 'available', path: claim.source_path, sha256: claim.source_sha256 }] },
  } as GovernedRunSummary);
}

describe('ResearchTrackingAssessment', () => {
  it('exposes the verified claim groups, outcomes, limits and allowed next step together', () => {
    render(<ResearchTrackingAssessment state={{ state: 'completed', decision: verified(decision), error: null }} evidenceCutoff="2026-10-30" primaryCounterevidence="Stress result failed." />);
    fireEvent.click(screen.getByText('Supporting evidence, counterevidence, limits and next validation'));
    expect(screen.getByText('Reviewed research result: not supported')).toBeInTheDocument();
    expect(screen.getByText(/Evidence through 2026-10-30/)).toBeInTheDocument();
    const section = screen.getByRole('region', { name: 'Research tracking assessment' });
    for (const heading of ['Supporting evidence', 'Gates', 'Counterevidence', 'Interpretation limits', 'Recorded failure modes', 'Next permitted validation']) {
      expect(within(section).getByRole('heading', { name: heading })).toBeInTheDocument();
    }
    for (const text of [claim.statement, decision.gates[0].statement, ...decision.interpretation_limits, ...decision.failure_modes, decision.next_permitted_validation_step]) {
      expect(within(section).getByText(text, { exact: false })).toBeInTheDocument();
    }
    expect(screen.getByText('blocked')).toBeInTheDocument();
    expect(screen.getAllByText('failed')).toHaveLength(2);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('keeps pending review distinct from a completed supported verdict', () => {
    const { rerender } = render(<ResearchTrackingAssessment state={{ state: 'pending', decision: verified({ ...decision, status: 'pending_review', verdict: 'blocked', gates: [decision.gates[1]], contradictory_evidence: [] }), error: null }} />);
    expect(screen.getByText(/Continuing effectiveness awaits review/)).toBeInTheDocument();
    expect(screen.queryByText(/Reviewed research result/)).not.toBeInTheDocument();
    rerender(<ResearchTrackingAssessment state={{ state: 'completed', decision: verified({ ...decision, verdict: 'supported', gates: [{ ...claim, claim_id: 'passing-gate' }], contradictory_evidence: [] }), error: null }} />);
    expect(screen.getByText('Reviewed research result: supported')).toBeInTheDocument();
    expect(screen.getByText(/does not establish a trading instruction/)).toBeInTheDocument();
  });

  it.each([
    [null, 'Loading verified assessment…'],
    [{ state: 'absent', decision: null, error: null }, 'No assessment is bound to this evidence bundle.'],
    [{ state: 'error', decision: null, error: 'PRIVATE exception /private/path' }, 'Assessment evidence could not be verified.'],
  ] as [DecisionLoadState | null, string][])('does not fabricate evidence for %s', (state, message) => {
    render(<ResearchTrackingAssessment state={state} />);
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.queryByText(/PRIVATE|retained failed gates/)).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Supporting evidence' })).not.toBeInTheDocument();
  });
});
