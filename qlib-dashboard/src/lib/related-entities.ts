import { loadRunSection, type GovernedRunSummary } from './governed-run';
import type { SecurityEvent, SecurityEvidence } from './security-evidence';

/**
 * Phase 3 cross-entity investigation derives instrument→model relations from
 * two governed sources only: exact bound formal events and each bound run's
 * latest published portfolio section. Holdings are never inferred from event
 * target weights, and a model is never borrowed from another market.
 */

export interface RelatedModelEventSummary {
  eventCount: number;
  /** Latest retained event action, with its exact ledger date. */
  lastAction: SecurityEvent['action'];
  lastEventDate: string;
}

export type RelatedHoldingState =
  | { status: 'loading' }
  | { status: 'held'; weight: number; asOf: string; cutoff: string; instrument: string }
  | { status: 'not_held'; asOf: string; cutoff: string }
  | { status: 'unavailable'; reason: string };

export interface RelatedModelEntry {
  modelVersionId: string;
  title: string;
  events: RelatedModelEventSummary | null;
  holding: RelatedHoldingState;
}

export interface LatestPortfolioSnapshot {
  asOf: string;
  /** Lower-cased published instrument identity → retained weight. */
  holdings: ReadonlyMap<string, { instrument: string; weight: number }>;
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const WEIGHT_TOLERANCE = 1e-6;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

/**
 * The instrument identities a published portfolio may use for the same
 * governed security: the catalog symbol, its display name and every published
 * alias. Matching is case-insensitive and stays inside one market because the
 * aliases come from that instrument's own catalog record.
 */
export function holdingAliases(
  evidence: Pick<SecurityEvidence, 'symbol' | 'name' | 'source_instruments'>,
): string[] {
  const values = [evidence.symbol, evidence.name, ...(evidence.source_instruments ?? [])];
  const seen = new Set<string>();
  for (const value of values) {
    const normalized = value.trim().toLowerCase();
    if (normalized) seen.add(normalized);
  }
  return [...seen];
}

/** Group exact bound events by model and retain the latest action date. */
export function summarizeModelEvents(
  events: readonly SecurityEvent[],
): Map<string, RelatedModelEventSummary> {
  const summaries = new Map<string, RelatedModelEventSummary>();
  for (const event of events) {
    const current = summaries.get(event.model_id);
    if (!current) {
      summaries.set(event.model_id, { eventCount: 1, lastAction: event.action, lastEventDate: event.time });
      continue;
    }
    current.eventCount += 1;
    // Events keep ledger order; a later date wins, and the last retained row
    // wins an exact-date tie without inventing an ordering.
    if (event.time >= current.lastEventDate) {
      current.lastAction = event.action;
      current.lastEventDate = event.time;
    }
  }
  return summaries;
}

/**
 * Parse the latest retained portfolio snapshot. A published section that does
 * not declare the research boundary, contains an invalid row or does not net
 * to one is rejected rather than partially rendered.
 */
export function parseLatestPortfolioSnapshot(payload: unknown): LatestPortfolioSnapshot {
  if (!isRecord(payload)) throw new Error('Published portfolio section is not an object.');
  if (payload.research_only !== true || payload.trade_ready !== false) {
    throw new Error('Published portfolio section does not declare the research-only boundary.');
  }
  if (!Array.isArray(payload.positions)) throw new Error('Published portfolio section has no positions.');
  let latest = '';
  const rows: Array<{ date: string; instrument: string; weight: number }> = [];
  for (const [index, raw] of payload.positions.entries()) {
    if (!isRecord(raw)) throw new Error(`Published portfolio position ${index} is not an object.`);
    const date = String(raw.date ?? '');
    const instrument = String(raw.instrument ?? '').trim();
    const weight = Number(raw.weight);
    if (!DATE.test(date) || !instrument || !Number.isFinite(weight)) {
      throw new Error(`Published portfolio position ${index} is invalid.`);
    }
    rows.push({ date, instrument, weight });
    if (date > latest) latest = date;
  }
  if (!latest) throw new Error('Published portfolio section has no dated positions.');

  const holdings = new Map<string, { instrument: string; weight: number }>();
  let total = 0;
  for (const row of rows) {
    if (row.date !== latest) continue;
    const key = row.instrument.toLowerCase();
    if (holdings.has(key)) {
      throw new Error(`Published portfolio holds ${row.instrument} twice on ${latest}.`);
    }
    holdings.set(key, { instrument: row.instrument, weight: row.weight });
    total += row.weight;
  }
  if (Math.abs(total - 1) > WEIGHT_TOLERANCE) {
    throw new Error(`Published portfolio net weight is ${total} on ${latest}; expected 1.`);
  }
  return { asOf: latest, holdings };
}

export function holdingForSnapshot(
  snapshot: LatestPortfolioSnapshot,
  aliases: readonly string[],
): { instrument: string; weight: number } | null {
  for (const alias of aliases) {
    const holding = snapshot.holdings.get(alias.toLowerCase());
    if (holding) return holding;
  }
  return null;
}

/**
 * Read one bound model's latest public portfolio section and report whether
 * the instrument is held. Every failure is an explicit unavailable state; the
 * caller keeps the event-derived relation and shows the reason.
 */
export async function readLatestPublishedHolding(
  run: GovernedRunSummary,
  aliases: readonly string[],
): Promise<RelatedHoldingState> {
  try {
    const payload = await loadRunSection(run, 'portfolio');
    const snapshot = parseLatestPortfolioSnapshot(payload);
    const holding = holdingForSnapshot(snapshot, aliases);
    const cutoff = run.evidenceCutoff;
    return holding
      ? { status: 'held', weight: holding.weight, asOf: snapshot.asOf, cutoff, instrument: holding.instrument }
      : { status: 'not_held', asOf: snapshot.asOf, cutoff };
  } catch (error) {
    return { status: 'unavailable', reason: error instanceof Error ? error.message : String(error) };
  }
}

/**
 * Build the related-model rows. A model is shown when it has exact bound
 * events or is held at the latest publication; a model with neither is not a
 * relation. The panel is empty when no row qualifies.
 */
export function buildRelatedModelEntries(
  boundModels: readonly GovernedRunSummary[],
  events: readonly SecurityEvent[],
  holdings: Readonly<Record<string, RelatedHoldingState>>,
): RelatedModelEntry[] {
  const summaries = summarizeModelEvents(events);
  const entries: RelatedModelEntry[] = [];
  for (const run of boundModels) {
    const summary = summaries.get(run.modelVersionId) ?? null;
    const holding = holdings[run.modelVersionId] ?? { status: 'loading' as const };
    if (!summary && holding.status !== 'held') continue;
    entries.push({ modelVersionId: run.modelVersionId, title: run.title, events: summary, holding });
  }
  return entries.sort((left, right) => {
    const count = (right.events?.eventCount ?? 0) - (left.events?.eventCount ?? 0);
    if (count !== 0) return count;
    const date = (right.events?.lastEventDate ?? '').localeCompare(left.events?.lastEventDate ?? '');
    if (date !== 0) return date;
    return left.title.localeCompare(right.title) || left.modelVersionId.localeCompare(right.modelVersionId);
  });
}
