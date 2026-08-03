import { describe, expect, it } from 'vitest';
import type { GovernedRunSummary } from './governed-run';
import { parseResearchDecision } from './model-run-decision';
import type { ModelRunBundleV2Manifest } from './model-run-bundle-v2';

const DIGEST = 'a'.repeat(64);
const BUNDLE = 'b'.repeat(64);

function run(): GovernedRunSummary {
  const manifest = {
    schema_version: '2.0.0',
    model_family_id: 'fixture-family',
    model_version_id: 'fixture-v1',
    run_id: 'fixture-run',
    bundle_id: BUNDLE,
    model_kind: 'cross_sectional_ranker',
    publication_channel: 'preview',
    publication_status: 'validated_preview',
    generated_at: '2026-08-03T00:00:00Z',
    evidence_cutoff: '2026-07-31',
    research_only: true,
    trade_ready: false,
    comparability_key: {
      market: 'us',
      benchmark_id: 'QQQ',
      trace_frequency: 'daily',
      currency: 'USD',
      return_basis: 'net',
      cost_basis: 'retained',
    },
    sections: [{
      section_id: 'summary',
      availability_status: 'available',
      required_for_model_kind: true,
      path: 'summary.json',
      sha256: DIGEST,
      byte_size: 10,
      reason: null,
    }],
  } as unknown as ModelRunBundleV2Manifest;
  return {
    key: 'preview:fixture-family:fixture-v1:fixture-run',
    modelFamilyId: 'fixture-family',
    modelVersionId: 'fixture-v1',
    runId: 'fixture-run',
    bundleId: BUNDLE,
    title: 'Fixture',
    modelKind: 'cross_sectional_ranker',
    channel: 'preview',
    publicationStatus: 'validated_preview',
    market: 'us',
    benchmark: 'QQQ',
    generatedAt: '2026-08-03T00:00:00Z',
    evidenceCutoff: '2026-07-31',
    evidenceStatus: 'complete',
    decisionStatus: 'absent',
    manifestPath: 'fixture/manifest.json',
    manifestSha256: DIGEST,
    summary: {},
    manifest,
    modelData: null,
    formalPackage: null,
    loadWarnings: [],
  };
}

function decision() {
  return {
    schema_version: '2.0.0',
    run_id: 'fixture-run',
    bundle_id: BUNDLE,
    verdict: 'supported',
    status: 'completed',
    gates: [{
      claim_id: 'minimum-evidence',
      outcome: 'passed',
      statement: 'The reviewed evidence gate passed.',
      source_path: 'summary.json',
      source_sha256: DIGEST,
    }],
    supporting_evidence: [],
    contradictory_evidence: [],
    interpretation_limits: ['Only the declared gate was evaluated.'],
    failure_modes: ['Future evidence may invalidate the conclusion.'],
    next_permitted_validation_step: 'Validate one additional held-out window.',
    research_only: true,
    trade_ready: false,
  };
}

describe('manifest-bound research decisions', () => {
  it('accepts a completed verdict only when every claim binds to the manifest', () => {
    const parsed = parseResearchDecision(decision(), run());
    expect(parsed.verdict).toBe('supported');
    expect(parsed.gates[0].source_sha256).toBe(DIGEST);
  });

  it('fails closed on evidence hash or bundle drift', () => {
    const wrongHash = decision();
    wrongHash.gates[0].source_sha256 = 'c'.repeat(64);
    expect(() => parseResearchDecision(wrongHash, run())).toThrow(/evidence binding failed/i);

    const wrongBundle = decision();
    wrongBundle.bundle_id = 'd'.repeat(64);
    expect(() => parseResearchDecision(wrongBundle, run())).toThrow(/bundle identity mismatch/i);
  });

  it('rejects verdicts that contradict gate outcomes', () => {
    const inconsistent = decision();
    inconsistent.gates[0].outcome = 'failed';
    expect(() => parseResearchDecision(inconsistent, run())).toThrow(/inconsistent with gates/i);

    const pending = decision();
    pending.status = 'pending_review';
    expect(() => parseResearchDecision(pending, run())).toThrow(/must remain blocked/i);
  });
});
