import type { CanonicalMetricV2, ModelRunSectionDeclaration } from './model-run-bundle-v2';
import { parseCanonicalMetricV2 } from './model-run-bundle-v2';
import { loadRunSection, type GovernedRunSummary } from './governed-run';
import type { Position, ReportRow } from './types';

export interface FormalPerformanceEvidence {
  benchmark: string;
  dateRange: { start: string; end: string };
  report: ReportRow[];
  traceFrequency: string;
}

export interface FormalRiskEvidence {
  metrics: CanonicalMetricV2[];
  interpretationLimit: string;
}

export interface FormalRobustnessEvidence {
  windowSummary: Array<Record<string, unknown>>;
  interpretationLimit: string;
}

export interface FormalPortfolioEvidence {
  contract: Record<string, unknown>;
  positions: Position[];
}

export interface FormalDiagnosticsEvidence {
  completeness: Record<string, unknown>;
  interpretationNotes: string[];
}

export interface FormalRunEvidence {
  run: GovernedRunSummary;
  metrics: CanonicalMetricV2[];
  performance: FormalPerformanceEvidence;
  risk: FormalRiskEvidence;
  robustness: FormalRobustnessEvidence;
  portfolio: FormalPortfolioEvidence;
  trades: Array<Record<string, unknown>>;
  attribution: Array<Record<string, unknown>>;
  diagnostics: FormalDiagnosticsEvidence;
  lineage: Record<string, unknown>;
  sectionReasons: Record<string, string>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`${label} must be a JSON object.`);
  if (value.research_only !== true || value.trade_ready !== false) {
    throw new Error(`${label} does not preserve the research-only boundary.`);
  }
  return value;
}

function records(value: unknown, label: string): Array<Record<string, unknown>> {
  if (!Array.isArray(value) || !value.every(isRecord)) throw new Error(`${label} must be a JSON array of objects.`);
  return value;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function canonicalMetrics(value: unknown, label: string): CanonicalMetricV2[] {
  if (!Array.isArray(value)) throw new Error(`${label} must declare canonical metrics.`);
  return value.map(parseCanonicalMetricV2);
}

function declaration(run: GovernedRunSummary, sectionId: string): ModelRunSectionDeclaration | null {
  return run.manifest?.sections.find((section) => section.section_id === sectionId) ?? null;
}

async function optionalSection(
  run: GovernedRunSummary,
  sectionId: string,
  reasons: Record<string, string>,
): Promise<unknown | null> {
  const declared = declaration(run, sectionId);
  if (!declared || declared.availability_status !== 'available') {
    reasons[sectionId] = declared?.reason || `${sectionId} is not declared by this bundle.`;
    return null;
  }
  return loadRunSection(run, sectionId);
}

function parseReport(value: unknown, benchmarkId: string): ReportRow[] {
  return records(value, 'performance.report').map((row, index) => {
    const account = Number(row.account);
    const date = String(row.date ?? '');
    if (!date || !Number.isFinite(account) || account <= 0) {
      throw new Error(`performance.report row ${index} has an invalid date or account value.`);
    }
    return { ...row, date, account, benchmark_id: benchmarkId } as ReportRow;
  });
}

function parsePositions(value: unknown): Position[] {
  const positions = records(value, 'portfolio.positions').map((row, index) => {
    const date = String(row.date ?? '');
    const instrument = String(row.instrument ?? '');
    const weight = Number(row.weight);
    if (!date || !instrument || !Number.isFinite(weight)) {
      throw new Error(`portfolio.positions row ${index} is invalid.`);
    }
    return { ...row, date, instrument, weight } as Position;
  });

  const dailyWeights = new Map<string, { total: number; instruments: Set<string> }>();
  for (const position of positions) {
    const day = dailyWeights.get(position.date) ?? { total: 0, instruments: new Set<string>() };
    if (day.instruments.has(position.instrument)) {
      throw new Error(`portfolio.positions contains duplicate ${position.instrument} on ${position.date}.`);
    }
    day.instruments.add(position.instrument);
    day.total += position.weight;
    dailyWeights.set(position.date, day);
  }
  for (const [date, day] of dailyWeights) {
    if (Math.abs(day.total - 1) > 1e-6) {
      throw new Error(`portfolio.positions net weight is ${day.total} on ${date}; expected 1.`);
    }
  }
  return positions;
}

export function metricById(metrics: CanonicalMetricV2[], metricId: string): CanonicalMetricV2 | null {
  return metrics.find((metric) => metric.metric_id === metricId) ?? null;
}

export async function loadFormalRunEvidence(run: GovernedRunSummary): Promise<FormalRunEvidence> {
  if (run.channel !== 'formal' || !run.manifest) {
    throw new Error('Formal backtest review only accepts a manifest-bound formal run.');
  }

  const sectionReasons: Record<string, string> = {};
  const [performanceRaw, riskRaw, robustnessRaw, portfolioRaw, tradesRaw, attributionRaw, diagnosticsRaw, lineageRaw] = await Promise.all([
    optionalSection(run, 'performance', sectionReasons),
    optionalSection(run, 'risk', sectionReasons),
    optionalSection(run, 'robustness', sectionReasons),
    optionalSection(run, 'portfolio', sectionReasons),
    optionalSection(run, 'trades', sectionReasons),
    optionalSection(run, 'attribution', sectionReasons),
    optionalSection(run, 'diagnostics', sectionReasons),
    optionalSection(run, 'lineage', sectionReasons),
  ]);

  if (!performanceRaw || !portfolioRaw) {
    throw new Error('The formal bundle does not retain the required performance and portfolio sections.');
  }

  const summary = record(run.summary, 'summary');
  const performance = record(performanceRaw, 'performance');
  const portfolio = record(portfolioRaw, 'portfolio');
  const risk = riskRaw ? record(riskRaw, 'risk') : null;
  const robustness = robustnessRaw ? record(robustnessRaw, 'robustness') : null;
  const diagnostics = diagnosticsRaw ? record(diagnosticsRaw, 'diagnostics') : null;
  const lineage = lineageRaw ? record(lineageRaw, 'lineage') : {};
  const dateRange = isRecord(performance.date_range) ? performance.date_range : {};
  const start = String(dateRange.start ?? run.manifest.comparability_key.start);
  const end = String(dateRange.end ?? run.manifest.comparability_key.end);
  const benchmark = String(performance.benchmark ?? run.benchmark);

  return {
    run,
    metrics: canonicalMetrics(summary.metrics, 'summary.metrics'),
    performance: {
      benchmark,
      dateRange: { start, end },
      report: parseReport(performance.report, benchmark),
      traceFrequency: String(performance.trace_frequency ?? run.manifest.comparability_key.trace_frequency),
    },
    risk: {
      metrics: risk ? canonicalMetrics(risk.metrics, 'risk.metrics') : [],
      interpretationLimit: String(risk?.interpretation_limit ?? sectionReasons.risk ?? ''),
    },
    robustness: {
      windowSummary: robustness ? records(robustness.window_summary, 'robustness.window_summary') : [],
      interpretationLimit: String(robustness?.interpretation_limit ?? sectionReasons.robustness ?? ''),
    },
    portfolio: {
      contract: isRecord(portfolio.portfolio_contract) ? portfolio.portfolio_contract : {},
      positions: parsePositions(portfolio.positions),
    },
    trades: tradesRaw ? records(tradesRaw, 'trades') : [],
    attribution: attributionRaw ? records(attributionRaw, 'attribution') : [],
    diagnostics: {
      completeness: diagnostics && isRecord(diagnostics.evidence_completeness)
        ? diagnostics.evidence_completeness
        : isRecord(summary.evidence_completeness) ? summary.evidence_completeness : {},
      interpretationNotes: diagnostics ? strings(diagnostics.interpretation_notes) : [],
    },
    lineage,
    sectionReasons,
  };
}
