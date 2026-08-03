import type { GovernedRunSummary } from './governed-run';
import { sha256Text } from './model-run-bundle-v2';

export type ResearchDecisionVerdict = 'supported' | 'not_supported' | 'blocked';
export type ResearchDecisionStatus = 'pending_review' | 'completed';
export type ResearchDecisionOutcome = 'passed' | 'failed' | 'blocked' | 'informational';

export interface ResearchDecisionClaim {
  claim_id: string;
  outcome: ResearchDecisionOutcome;
  statement: string;
  source_path: string;
  source_sha256: string;
}

export interface ResearchDecisionReceipt {
  schema_version: '2.0.0';
  run_id: string;
  bundle_id: string;
  verdict: ResearchDecisionVerdict;
  status: ResearchDecisionStatus;
  gates: ResearchDecisionClaim[];
  supporting_evidence: ResearchDecisionClaim[];
  contradictory_evidence: ResearchDecisionClaim[];
  interpretation_limits: string[];
  failure_modes: string[];
  next_permitted_validation_step: string;
  research_only: true;
  trade_ready: false;
}

interface DecisionCatalogRecord {
  run_id: string;
  bundle_id: string;
  status: ResearchDecisionStatus;
  verdict: ResearchDecisionVerdict;
  path: string;
  sha256: string;
  byte_size: number;
}

interface DecisionCatalog {
  schema_version: '2.0.0';
  generated_at: string;
  records: DecisionCatalogRecord[];
  research_only: true;
  trade_ready: false;
}

export type DecisionLoadState =
  | { state: 'absent'; decision: null; error: null }
  | { state: 'pending'; decision: ResearchDecisionReceipt; error: null }
  | { state: 'completed'; decision: ResearchDecisionReceipt; error: null }
  | { state: 'error'; decision: null; error: string };

const SHA256 = /^[a-f0-9]{64}$/;
const VERDICTS = new Set<ResearchDecisionVerdict>(['supported', 'not_supported', 'blocked']);
const STATUSES = new Set<ResearchDecisionStatus>(['pending_review', 'completed']);
const OUTCOMES = new Set<ResearchDecisionOutcome>(['passed', 'failed', 'blocked', 'informational']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function requireValue(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function safePath(value: unknown, label: string): string {
  const path = String(value ?? '');
  requireValue(path.endsWith('.json') && !path.startsWith('/') && !path.includes('..') && !path.includes('\\'), `Invalid ${label}`);
  return path;
}

function decisionAssetRoot(): string {
  const base = import.meta.env.BASE_URL.endsWith('/') ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;
  return `${base}data/model-decisions/`;
}

async function fetchText(path: string): Promise<string> {
  const response = await fetch(`${decisionAssetRoot()}${path}`, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`Decision asset request failed (${response.status}): ${path}`);
  return response.text();
}

function parseClaim(value: unknown): ResearchDecisionClaim {
  requireValue(isRecord(value), 'Decision claim is invalid');
  const outcome = String(value.outcome) as ResearchDecisionOutcome;
  requireValue(OUTCOMES.has(outcome), 'Decision claim outcome is invalid');
  const digest = String(value.source_sha256 ?? '');
  requireValue(SHA256.test(digest), 'Decision claim source hash is invalid');
  const claim: ResearchDecisionClaim = {
    claim_id: String(value.claim_id ?? ''),
    outcome,
    statement: String(value.statement ?? ''),
    source_path: safePath(value.source_path, 'claim source path'),
    source_sha256: digest,
  };
  requireValue(Boolean(claim.claim_id && claim.statement.trim()), 'Decision claim identity or statement is missing');
  return claim;
}

function parseStringList(value: unknown, label: string): string[] {
  requireValue(Array.isArray(value) && value.every((row) => typeof row === 'string' && row.trim()), `${label} is invalid`);
  return value as string[];
}

export function parseResearchDecision(value: unknown, run: GovernedRunSummary): ResearchDecisionReceipt {
  requireValue(isRecord(value), 'Research decision receipt is invalid');
  requireValue(value.schema_version === '2.0.0', 'Unsupported decision schema');
  const verdict = String(value.verdict) as ResearchDecisionVerdict;
  const status = String(value.status) as ResearchDecisionStatus;
  requireValue(VERDICTS.has(verdict) && STATUSES.has(status), 'Decision verdict or status is invalid');
  requireValue(value.research_only === true && value.trade_ready === false, 'Decision research boundary is invalid');
  requireValue(Boolean(run.bundleId && value.bundle_id === run.bundleId), 'Decision bundle identity mismatch');
  requireValue(value.run_id === run.runId, 'Decision run identity mismatch');
  requireValue(Boolean(run.manifest), 'Decision requires a verified Bundle v2 manifest');
  const sections = new Map(
    run.manifest!.sections
      .filter((section) => section.availability_status === 'available' && section.path && section.sha256)
      .map((section) => [section.path!, section.sha256!]),
  );
  const gates = Array.isArray(value.gates) ? value.gates.map(parseClaim) : [];
  const supporting = Array.isArray(value.supporting_evidence) ? value.supporting_evidence.map(parseClaim) : [];
  const contradictory = Array.isArray(value.contradictory_evidence) ? value.contradictory_evidence.map(parseClaim) : [];
  requireValue(gates.length > 0, 'Decision must declare at least one gate');
  const claims = [...gates, ...supporting, ...contradictory];
  requireValue(new Set(claims.map((claim) => claim.claim_id)).size === claims.length, 'Decision claim IDs are duplicated');
  claims.forEach((claim) => {
    requireValue(sections.get(claim.source_path) === claim.source_sha256, `Decision evidence binding failed: ${claim.source_path}`);
  });
  if (status === 'pending_review') requireValue(verdict === 'blocked', 'Pending decision must remain blocked');
  if (verdict === 'supported') {
    requireValue(status === 'completed' && gates.every((gate) => gate.outcome === 'passed'), 'Supported verdict is inconsistent with gates');
    requireValue(!claims.some((claim) => claim.outcome === 'failed' || claim.outcome === 'blocked'), 'Supported verdict contains adverse evidence');
  } else if (verdict === 'not_supported') {
    requireValue(status === 'completed' && gates.some((gate) => gate.outcome === 'failed'), 'Not-supported verdict requires a failed gate');
  } else {
    requireValue(gates.some((gate) => gate.outcome === 'blocked'), 'Blocked verdict requires a blocked gate');
  }
  const next = String(value.next_permitted_validation_step ?? '');
  requireValue(Boolean(next.trim()), 'Next permitted validation step is missing');
  return {
    schema_version: '2.0.0',
    run_id: run.runId,
    bundle_id: run.bundleId!,
    verdict,
    status,
    gates,
    supporting_evidence: supporting,
    contradictory_evidence: contradictory,
    interpretation_limits: parseStringList(value.interpretation_limits, 'Interpretation limits'),
    failure_modes: parseStringList(value.failure_modes, 'Failure modes'),
    next_permitted_validation_step: next,
    research_only: true,
    trade_ready: false,
  };
}

function parseCatalog(value: unknown): DecisionCatalog {
  requireValue(isRecord(value) && value.schema_version === '2.0.0', 'Decision catalog is invalid');
  requireValue(value.research_only === true && value.trade_ready === false && Array.isArray(value.records), 'Decision catalog boundary is invalid');
  const identities = new Set<string>();
  const records = value.records.map((raw): DecisionCatalogRecord => {
    requireValue(isRecord(raw), 'Decision catalog record is invalid');
    const runId = String(raw.run_id ?? '');
    const bundleId = String(raw.bundle_id ?? '');
    const digest = String(raw.sha256 ?? '');
    const status = String(raw.status) as ResearchDecisionStatus;
    const verdict = String(raw.verdict) as ResearchDecisionVerdict;
    requireValue(Boolean(runId) && SHA256.test(bundleId) && SHA256.test(digest), 'Decision catalog identity is invalid');
    requireValue(STATUSES.has(status) && VERDICTS.has(verdict), 'Decision catalog state is invalid');
    requireValue(!identities.has(bundleId), 'Decision catalog contains duplicate bundle identity');
    identities.add(bundleId);
    requireValue(Number.isInteger(raw.byte_size) && Number(raw.byte_size) >= 0, 'Decision catalog byte size is invalid');
    return {
      run_id: runId,
      bundle_id: bundleId,
      status,
      verdict,
      path: safePath(raw.path, 'decision path'),
      sha256: digest,
      byte_size: Number(raw.byte_size),
    };
  });
  return {
    schema_version: '2.0.0',
    generated_at: String(value.generated_at ?? ''),
    records,
    research_only: true,
    trade_ready: false,
  };
}

export async function loadDecisionForRun(run: GovernedRunSummary): Promise<DecisionLoadState> {
  if (!run.bundleId || !run.manifest) return { state: 'absent', decision: null, error: null };
  try {
    const catalog = parseCatalog(JSON.parse(await fetchText('catalog.json')) as unknown);
    const record = catalog.records.find((candidate) => candidate.bundle_id === run.bundleId);
    if (!record) return { state: 'absent', decision: null, error: null };
    requireValue(record.run_id === run.runId, 'Decision catalog run identity mismatch');
    const text = await fetchText(record.path);
    requireValue(new TextEncoder().encode(text).byteLength === record.byte_size, 'Decision byte size mismatch');
    requireValue((await sha256Text(text)) === record.sha256, 'Decision SHA-256 mismatch');
    const decision = parseResearchDecision(JSON.parse(text) as unknown, run);
    requireValue(decision.status === record.status && decision.verdict === record.verdict, 'Decision catalog/receipt state mismatch');
    return { state: decision.status === 'completed' ? 'completed' : 'pending', decision, error: null };
  } catch (error) {
    return { state: 'error', decision: null, error: error instanceof Error ? error.message : String(error) };
  }
}
