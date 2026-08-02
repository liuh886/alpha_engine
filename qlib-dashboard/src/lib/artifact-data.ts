import type { ModelData } from './data-parser';
import type { BundleArtifact, OpenedResearchBundle } from './research-bundle';

export interface EvidenceArtifactGroup {
  kind: string;
  count: number;
  bytes: number;
  required: number;
}

export function groupArtifacts(artifacts: BundleArtifact[]): EvidenceArtifactGroup[] {
  const groups = new Map<string, EvidenceArtifactGroup>();
  for (const artifact of artifacts) {
    const current = groups.get(artifact.kind) ?? { kind: artifact.kind, count: 0, bytes: 0, required: 0 };
    current.count += 1;
    current.bytes += artifact.byte_size;
    if (artifact.required) current.required += 1;
    groups.set(artifact.kind, current);
  }
  return Array.from(groups.values()).sort((a, b) => b.bytes - a.bytes || a.kind.localeCompare(b.kind));
}

export function findArtifact(bundle: OpenedResearchBundle | null, predicate: (artifact: BundleArtifact) => boolean): BundleArtifact | null {
  return bundle?.manifest.artifacts.find(predicate) ?? null;
}

export async function readArtifactText(bundle: OpenedResearchBundle, artifact: BundleArtifact): Promise<string> {
  return (await bundle.source.read(artifact.path)).text();
}

export async function readArtifactJson<T>(bundle: OpenedResearchBundle, artifact: BundleArtifact): Promise<T> {
  return JSON.parse(await readArtifactText(bundle, artifact)) as T;
}

export function numericMetric(model: ModelData, aliases: string[]): number | null {
  for (const key of aliases) {
    const value = model.metrics?.[key] ?? model.backtest?.metrics?.[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

export interface SignalExecutionRow {
  symbol: string;
  signalDate: string;
  executionDate: string;
  action: string;
  weight?: number;
}

function normalizeLedgerRow(row: Record<string, unknown>): SignalExecutionRow | null {
  const signalDate = String(row.signal_date ?? row.signalDate ?? row.decision_date ?? '');
  const executionDate = String(row.execution_date ?? row.executionDate ?? row.trade_date ?? '');
  if (!signalDate || !executionDate) return null;
  return {
    symbol: String(row.symbol ?? row.instrument ?? row.code ?? 'Portfolio'),
    signalDate,
    executionDate,
    action: String(row.action ?? row.side ?? row.event ?? 'rebalance'),
    weight: typeof row.weight === 'number' ? row.weight : typeof row.target_weight === 'number' ? row.target_weight : undefined,
  };
}

export function extractSignalExecutionRows(model: ModelData): SignalExecutionRow[] {
  const candidates: unknown[] = [];
  const params = model.params as Record<string, unknown> | undefined;
  const backtest = model.backtest as unknown as Record<string, unknown> | undefined;
  for (const value of [
    params?.signal_execution_ledger,
    params?.trade_ledger,
    backtest?.signal_execution_ledger,
    backtest?.trade_ledger,
    backtest?.positions,
  ]) {
    if (Array.isArray(value)) candidates.push(...value);
  }
  return candidates
    .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object')
    .map(normalizeLedgerRow)
    .filter((row): row is SignalExecutionRow => row !== null)
    .sort((a, b) => a.executionDate.localeCompare(b.executionDate));
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
