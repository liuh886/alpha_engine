import { describe, expect, it } from 'vitest';
import { buildDailyResearchSummary, escapeMarkdownInline, type DailyResearchSummaryEntry } from './research-summary';
import type { GovernedRunSummary } from './governed-run';
import {
  describeStrategyObservation,
  parseStrategyOperationsSnapshot,
  type StrategyObservationBrief,
} from './strategy-operations';

const generatedAt = new Date('2026-11-13T14:05:00Z');
const FACTOR_HASH = 'a'.repeat(64);

function makeRun(overrides: Partial<GovernedRunSummary>): GovernedRunSummary {
  return {
    key: 'formal:family:model:run',
    modelFamilyId: 'family',
    modelVersionId: 'model',
    runId: 'run',
    bundleId: null,
    title: 'Strategy',
    modelKind: 'forecast_model',
    channel: 'formal',
    publicationStatus: 'accepted_formal_baseline',
    market: 'us',
    benchmark: 'QQQ',
    generatedAt: '2026-11-13T00:00:00Z',
    evidenceCutoff: '2026-10-31',
    evidenceStatus: 'complete',
    decisionStatus: 'supported',
    manifestPath: null,
    manifestSha256: null,
    summary: {},
    manifest: null,
    loadWarnings: [],
    ...overrides,
  };
}

function factorEvidence(index: number) {
  return {
    factor_id: `/PRIVATE-FACTOR-${index}/`,
    factor_version: 'v1',
    implementation_hash: FACTOR_HASH,
    display_name: `Factor ${index}`,
    information_family: 'price',
    value: index / 10,
    reference: { note: '/PRIVATE-REFERENCE/' },
    state: 'positive',
    effect: 'support',
    reason_code: '/PRIVATE-REASON/',
    observed_at: '2026-10-30',
  };
}

const privateSnapshot = parseStrategyOperationsSnapshot({
  model_version_id: 'model-access',
  strategy_id: 'strategy-access',
  status: 'current_no_change',
  as_of: '2026-10-30',
  latest_completed_session: '2026-10-30',
  evaluation_changed: true,
  data_freshness: 'current',
  factor_freshness: 'unknown',
  decision_cadence: 'Every completed session',
  next_decision_policy: 'Next completed session',
  state_label: '/PRIVATE-STATE/',
  decision_reason: '/PRIVATE-DECISION/',
  delivery_status: 'sent',
  source_label: '/PRIVATE-SOURCE/',
  note: '/PRIVATE-NOTE/',
  turnover: 0.42,
  estimated_cost: 7,
  source_href: 'https://example.test/PRIVATE-HREF',
  allocations: [{ asset: '/PRIVATE-ALLOC/', current: 0.1, target: 0.4, delta: 0.3 }],
  factor_evidence: [factorEvidence(1)],
  source_identity: { formal_evidence_cutoff: '2026-09-30', formal_run_id: '/PRIVATE-RUN/' },
});

const accessEntry: DailyResearchSummaryEntry = {
  run: makeRun({
    key: 'formal:access:model:run',
    modelVersionId: 'model-access',
    title: 'Defensive rotation',
    market: 'cn',
    evidenceCutoff: '2026-09-30',
  }),
  snapshot: undefined,
  brief: describeStrategyObservation(privateSnapshot, false),
};

const permittedEntry: DailyResearchSummaryEntry = {
  run: makeRun({
    key: 'formal:permitted:model:run',
    modelVersionId: 'model-permitted',
    title: 'Momentum rotation',
    market: 'us',
    evidenceCutoff: '2026-10-31',
  }),
  snapshot: privateSnapshot,
  brief: {
    kind: 'changed',
    label: 'Changed at last evaluation',
    reason: 'Volatility eased',
    nextStep: 'Next completed session',
    recovery: null,
  },
};

describe('escapeMarkdownInline', () => {
  it.each([
    ['- x', '\\- x'],
    ['# x', '\\# x'],
    ['1. x', '1\\. x'],
    ['1) x', '1\\) x'],
    ['> x', '\\> x'],
    ['`x`', '\\`x\\`'],
    ['[x](y)', '\\[x\\](y)'],
    ['+ x', '\\+ x'],
    ['= x', '\\= x'],
    ['~ x', '\\~ x'],
    ['*emphasis*', '\\*emphasis*'],
    ['_emphasis_', '\\_emphasis_'],
  ])('escapes %s so it cannot open Markdown structure', (input, expected) => {
    expect(escapeMarkdownInline(input)).toBe(expected);
  });

  it('keeps ordinary prose byte-identical', () => {
    const prose = "QQQ's 3-day +12.5% target / rotation (a_b)";
    expect(escapeMarkdownInline(prose)).toBe(prose);
  });

  it('leaves non-structural leading signs unchanged', () => {
    expect(escapeMarkdownInline('-5.2% drawdown')).toBe('-5.2% drawdown');
    expect(escapeMarkdownInline('+3 allocations')).toBe('+3 allocations');
  });
});

describe('buildDailyResearchSummary', () => {
  it('builds the permitted and access-denied brief without unrendered private fields', () => {
    const markdown = buildDailyResearchSummary([accessEntry, permittedEntry], { generatedAt });

    expect(markdown).toContain('# Daily research summary — 2026-11-13 (UTC)');
    expect(markdown).toContain('1 changed · 0 unchanged · 0 retained · 0 need attention · 1 require access · 0 awaiting verification');

    expect(markdown).toContain('## Defensive rotation (CN · formal evidence through 2026-09-30)');
    expect(markdown).toContain('- Observation: Access required');
    expect(markdown).toContain('- Why: Current observations require strategy access.');
    expect(markdown).toContain('- Evidence: Formal evidence through 2026-09-30; current observation not verified');
    expect(markdown).toContain('- Risk: Review state not verified');
    expect(markdown).toContain('- Next review: Review schedule not verified');

    expect(markdown).toContain('## Momentum rotation (US · formal evidence through 2026-10-31)');
    expect(markdown).toContain('- Observation: Changed at last evaluation');
    expect(markdown).toContain('- Why: Volatility eased');
    expect(markdown).toContain('- Evidence: Observed 2026-10-30 · target dated 2026-10-30 · formal evidence 2026-10-31');
    expect(markdown).toContain('  - Factor 1: positive · support · observed 2026-10-30');
    expect(markdown).toContain('- Risk: Scheduled cadence');
    expect(markdown).toContain('- Next review: Next completed session');
    expect(markdown).toContain('Research evidence only — not an order or live market feed.');

    for (const sentinel of ['/PRIVATE-DECISION/', '/PRIVATE-FACTOR/', '/PRIVATE-ALLOC/',
      '/PRIVATE-NOTE/', '/PRIVATE-HREF/', '/PRIVATE-STATE/', '/PRIVATE-SOURCE/', '/PRIVATE-RUN/']) {
      expect(markdown).not.toContain(sentinel);
    }
  });

  it('includes available observation dates and no more than three factor lines', () => {
    const markdown = buildDailyResearchSummary([{
      ...permittedEntry,
      snapshot: parseStrategyOperationsSnapshot({
        model_version_id: 'model-permitted',
        strategy_id: 'strategy-permitted',
        status: 'current_no_change',
        as_of: '2026-10-29',
        latest_completed_session: '2026-10-30',
        evaluation_changed: true,
        data_freshness: 'current',
        factor_freshness: 'unknown',
        decision_cadence: 'Every completed session',
        next_decision_policy: 'Next completed session',
        state_label: 'Transition',
        decision_reason: 'Volatility eased',
        delivery_status: 'sent',
        source_label: 'Verified ledger',
        note: 'Research observation',
        allocations: [],
        decision_schedule: { signal_date: '2026-10-29', completed_through: '2026-11-01',
          cadence_sessions: 10, sessions_until_due: 4, state: 'within_cadence', execution_pending: false },
        factor_evidence: [factorEvidence(1), factorEvidence(2), factorEvidence(3), factorEvidence(4)],
        source_identity: { formal_evidence_cutoff: '2026-10-31' },
      }),
    }], { generatedAt });

    expect(markdown).toContain('- Evidence: Observed 2026-10-30 · target dated 2026-10-29 '
      + '· completed market through 2026-11-01 · formal evidence 2026-10-31');
    expect(markdown).toContain('  - Factor 3: positive · support · observed 2026-10-30');
    expect(markdown).not.toContain('Factor 4');
  });

  it('marks recovery risk and lists other strategies without their reasons', () => {
    const attentionBrief: StrategyObservationBrief = {
      kind: 'attention',
      label: 'Stale',
      reason: 'Source observation delayed',
      nextStep: 'Check the source run before retrying.',
      recovery: 'source',
    };
    const entries: DailyResearchSummaryEntry[] = [
      accessEntry,
      permittedEntry,
      { run: makeRun({ key: 'attention', title: 'Attention rotation' }), brief: attentionBrief },
      { run: makeRun({ key: 'fourth', title: 'Fourth strategy' }),
        brief: { kind: 'unchanged', label: 'Unchanged at last evaluation', reason: 'Fourth reason', nextStep: 'Next completed session', recovery: null } },
    ];
    const markdown = buildDailyResearchSummary(entries, { generatedAt });

    expect(markdown).toContain('- Risk: Action required');
    expect(markdown).toContain('- Next review: Check the source run before retrying.');
    expect(markdown).toContain('## Other formal strategies');
    expect(markdown).toContain('- Fourth strategy: Unchanged at last evaluation (formal evidence through 2026-10-31)');
    expect(markdown).not.toContain('Fourth reason');
  });

  it('collapses line breaks and control whitespace in dynamic strings', () => {
    const entry: DailyResearchSummaryEntry = {
      run: makeRun({ title: 'Momentum\n## Injected', key: 'sanitize' }),
      brief: {
        kind: 'unchanged',
        label: 'Unchanged\tat last evaluation',
        reason: 'First line\n- Forged bullet\r\nSecond',
        nextStep: 'Next\nreview',
        recovery: null,
      },
    };
    const markdown = buildDailyResearchSummary([entry], { generatedAt });
    const lines = markdown.split('\n');

    expect(markdown).toContain('## Momentum ## Injected (US · formal evidence through 2026-10-31)');
    expect(markdown).toContain('- Observation: Unchanged at last evaluation');
    expect(markdown).toContain('- Why: First line - Forged bullet Second');
    expect(markdown).toContain('- Next review: Next review');
    expect(lines).not.toContain('## Injected');
    expect(lines).not.toContain('- Forged bullet');
  });

  it('keeps the copied brief structure when dynamic values begin with Markdown markers', () => {
    const entry: DailyResearchSummaryEntry = {
      run: makeRun({ key: 'escape', title: '- Injected heading' }),
      brief: {
        kind: 'changed',
        label: '1. Injected label',
        reason: '# Injected reason with `code` and [link](https://example.test)',
        nextStep: '> Injected review',
        recovery: null,
      },
    };
    const markdown = buildDailyResearchSummary([entry], { generatedAt });
    const lines = markdown.split('\n');

    expect(markdown).toContain('## \\- Injected heading (US · formal evidence through 2026-10-31)');
    expect(markdown).toContain('- Observation: 1\\. Injected label');
    expect(markdown).toContain('- Why: \\# Injected reason with \\`code\\` and \\[link\\](https://example.test)');
    expect(markdown).toContain('- Next review: \\> Injected review');
    expect(lines.filter((line) => /^#{1,6}\s/.test(line))).toHaveLength(2);
    expect(lines.filter((line) => line.startsWith('- '))).toHaveLength(5);
  });
});
