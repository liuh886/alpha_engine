import { describe, expect, it } from 'vitest';
import { rdiFixture } from '@/test/rdi-fixture';
import { parseRdiResearch, rdiEvidenceUrl } from './rdi-research';

describe('RDI reviewed evidence boundary', () => {
  it('reads the build projection with explicit dated research scope', () => {
    const result = parseRdiResearch(rdiFixture);
    expect(result.status).toBe('not_validated');
    expect(result.historical_comparison.map(row => row.horizon_sessions)).toEqual([7, 14, 28]);
    expect(rdiEvidenceUrl(result.protocol_path, result.repository_commit)).toContain(`/blob/${result.repository_commit}/docs/`);
  });
  it.each([
    { trade_ready: true }, { research_only: false }, { status: 'validated' },
    { repository_commit: 'main' }, { historical_comparison: [] },
    { evidence: [{ path: 'docs/../../secret', sha256: 'a'.repeat(64) }] },
    { historical_comparison: [{ ...rdiFixture.historical_comparison[0], drawdown_loss_frequency: 1.1 }] },
  ])('rejects unsupported or contradictory claims: %j', change => {
    expect(() => parseRdiResearch({ ...rdiFixture, ...change })).toThrow();
  });
  it('accepts mismatch only without historical statistics', () => {
    expect(() => parseRdiResearch({ ...rdiFixture, status: 'evidence_mismatch' })).toThrow();
    expect(parseRdiResearch({ ...rdiFixture, status: 'evidence_mismatch', historical_comparison: [] }).status).toBe('evidence_mismatch');
  });
  it('rejects unsafe or mutable evidence links', () => {
    expect(() => rdiEvidenceUrl('https://example.com', rdiFixture.repository_commit)).toThrow();
    expect(() => rdiEvidenceUrl(rdiFixture.protocol_path, 'main')).toThrow();
  });
});
