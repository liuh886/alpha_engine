import { readFileSync } from 'node:fs';
import { rdiFixture } from '../src/test/rdi-fixture';

// TEST ONLY: interaction data never comes from the optional published asset.
// Reuse the committed descriptive archive for distinguishable horizon values;
// source identities and inventory below are explicitly synthetic test records.
const archivedControl = JSON.parse(readFileSync(new URL(
  '../../docs/evidence/ashare_rdi_phase2/csi300_price_only_descriptive_2026-10-24.json', import.meta.url,
), 'utf8')) as {
  last_price_session: string;
  rows: number;
  results: { horizon_sessions: number; drawdown_at_least_threshold: { p_severe_loss: number; observations: number };
    other: { p_severe_loss: number; observations: number } }[];
};

export const rdiInteractionFixture = {
  ...rdiFixture,
  reviewed_at: '2026-10-24',
  reviewed_price_cutoff: archivedControl.last_price_session,
  reviewed_price_rows: archivedControl.rows,
  event_families: [
    { id: 'synthetic_disclosures', source: 'TEST ONLY synthetic disclosure adapter', readiness: 'partial', historical_pit_verified: false },
    { id: 'synthetic_policy', source: 'TEST ONLY synthetic policy source', readiness: 'not_integrated', historical_pit_verified: false },
    { id: 'synthetic_external', source: 'TEST ONLY synthetic external source', readiness: 'not_integrated', historical_pit_verified: false },
  ],
  historical_comparison: archivedControl.results.map(row => ({
    horizon_sessions: row.horizon_sessions,
    drawdown_loss_frequency: row.drawdown_at_least_threshold.p_severe_loss,
    other_loss_frequency: row.other.p_severe_loss,
    drawdown_observations: row.drawdown_at_least_threshold.observations,
    other_observations: row.other.observations,
  })),
};
