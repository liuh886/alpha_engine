export interface RdiResearchBriefing {
  status: 'not_validated' | 'evidence_mismatch';
  repository_commit: string;
  price_source_git_blob_sha1: string;
  reviewed_at: string;
  reviewed_price_cutoff: string;
  reviewed_price_rows: number;
  event_families: { id: string; source: string; readiness: string; historical_pit_verified: boolean }[];
  sector_candidates: { symbol: string; sector: string; admitted: false }[];
  historical_comparison: { horizon_sessions: number; drawdown_loss_frequency: number; other_loss_frequency: number;
    drawdown_observations: number; other_observations: number }[];
  evidence: { path: string; sha256: string }[];
  protocol_path: string;
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
const positiveInteger = (value: unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
const frequency = (value: unknown) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
const date = (value: unknown) => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
const repoPath = (value: unknown) => typeof value === 'string' && /^(docs|configs|data)\/[\w/.-]+$/.test(value)
  && !value.split('/').includes('..');

export function parseRdiResearch(value: unknown): RdiResearchBriefing {
  if (!object(value) || value.schema_version !== '1.0.0' || value.research_only !== true || value.trade_ready !== false
    || !['not_validated', 'evidence_mismatch'].includes(String(value.status))
    || value.benchmark !== 'CSI300 / 000300.SH' || !date(value.reviewed_at) || !date(value.reviewed_price_cutoff)
    || typeof value.repository_commit !== 'string' || !/^[a-f0-9]{40}$/.test(value.repository_commit)
    || typeof value.price_source_git_blob_sha1 !== 'string' || !/^[a-f0-9]{40}$/.test(value.price_source_git_blob_sha1)
    || !positiveInteger(value.reviewed_price_rows) || !repoPath(value.protocol_path)
    || !Array.isArray(value.event_families) || !value.event_families.length
    || !Array.isArray(value.sector_candidates) || !value.sector_candidates.length
    || !Array.isArray(value.historical_comparison) || !Array.isArray(value.evidence) || !value.evidence.length) {
    throw new Error('RDI reviewed evidence is unavailable.');
  }
  for (const family of value.event_families) {
    if (!object(family) || typeof family.id !== 'string' || !family.id || typeof family.source !== 'string'
      || typeof family.readiness !== 'string' || typeof family.historical_pit_verified !== 'boolean') {
      throw new Error('RDI source inventory is invalid.');
    }
  }
  for (const sector of value.sector_candidates) {
    if (!object(sector) || typeof sector.symbol !== 'string' || typeof sector.sector !== 'string' || sector.admitted !== false) {
      throw new Error('RDI sector admission is invalid.');
    }
  }
  if (value.status === 'evidence_mismatch' && value.historical_comparison.length
    || value.status === 'not_validated' && value.historical_comparison.map(row => object(row) && row.horizon_sessions).join(',') !== '7,14,28') {
    throw new Error('RDI historical comparison is inconsistent.');
  }
  for (const row of value.historical_comparison) {
    if (!object(row) || !frequency(row.drawdown_loss_frequency) || !frequency(row.other_loss_frequency)
      || !positiveInteger(row.drawdown_observations) || !positiveInteger(row.other_observations)) {
      throw new Error('RDI historical comparison is invalid.');
    }
  }
  for (const evidence of value.evidence) {
    if (!object(evidence) || !repoPath(evidence.path) || typeof evidence.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(evidence.sha256)) {
      throw new Error('RDI source reference is invalid.');
    }
  }
  return value as unknown as RdiResearchBriefing;
}

export async function fetchRdiResearch(signal: AbortSignal): Promise<RdiResearchBriefing> {
  const response = await fetch(`${import.meta.env.BASE_URL}data/strategy-operations/rdi-research.json`, { cache: 'no-store', signal });
  if (!response.ok) throw new Error('RDI reviewed evidence is unavailable.');
  return parseRdiResearch(await response.json());
}

export function rdiEvidenceUrl(path: string, commit: string) {
  if (!repoPath(path) || !/^[a-f0-9]{40}$/.test(commit)) throw new Error('Invalid RDI evidence path.');
  return `https://github.com/liuh886/alpha_engine/blob/${commit}/${path}`;
}
