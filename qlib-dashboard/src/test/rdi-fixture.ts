// Synthetic contract values, not market evidence. Optional asset availability
// must not determine whether the isolated UI state tests can run.
export const rdiFixture = {
  schema_version: '1.0.0', research_only: true, trade_ready: false,
  status: 'not_validated', benchmark: 'CSI300 / 000300.SH',
  repository_commit: 'a'.repeat(40), price_source_git_blob_sha1: 'b'.repeat(40),
  reviewed_at: '2020-02-03', reviewed_price_cutoff: '2020-01-31', reviewed_price_rows: 300,
  event_families: [{ id: 'holding_change', source: 'Synthetic source', readiness: 'partial', historical_pit_verified: false }],
  sector_candidates: [{ symbol: 'FIXTURE.SH', sector: 'synthetic', admitted: false }],
  historical_comparison: [7, 14, 28].map(horizon_sessions => ({
    horizon_sessions, drawdown_loss_frequency: 0.2, other_loss_frequency: 0.1,
    drawdown_observations: 100, other_observations: 200,
  })),
  evidence: [{ path: 'docs/evidence/synthetic.json', sha256: 'c'.repeat(64) }],
  protocol_path: 'docs/research/ashare_rdi_phase2_protocol.md',
};
