import type { GovernedRunSummary } from './governed-run';
import type { StrategyObservationBrief, StrategyOperationsSnapshot } from './strategy-operations';

export interface DailyResearchSummaryEntry {
  run: GovernedRunSummary;
  snapshot?: StrategyOperationsSnapshot;
  brief: StrategyObservationBrief;
}

export interface DailyResearchSummaryOptions {
  generatedAt: Date;
}

const PRIORITY_COUNT = 3;
const FACTOR_LINE_COUNT = 3;
const FOOTER = 'Research evidence only — not an order or live market feed.';
const UNVERIFIED_REVIEW_RISK = 'Review state not verified';
const UNVERIFIED_REVIEW_SCHEDULE = 'Review schedule not verified';

/** Collapse line breaks and control whitespace so dynamic copy cannot break Markdown structure. */
function sanitize(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

function summaryDate(generatedAt: Date): string {
  const date = Number.isNaN(generatedAt.getTime()) ? new Date() : generatedAt;
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

function evidenceLines(entry: DailyResearchSummaryEntry): string[] {
  const { run, snapshot } = entry;
  if (!snapshot) {
    return [`- Evidence: Formal evidence through ${sanitize(run.evidenceCutoff)}; current observation not verified`];
  }
  const observations = [
    `Observed ${sanitize(snapshot.latestCompletedSession ?? 'unknown')}`,
    `target dated ${sanitize(snapshot.decisionSchedule?.signalDate ?? snapshot.asOf ?? 'unknown')}`,
    ...(snapshot.decisionSchedule?.completedThrough
      ? [`completed market through ${sanitize(snapshot.decisionSchedule.completedThrough)}`]
      : []),
    `formal evidence ${sanitize(run.evidenceCutoff)}`,
  ].join(' · ');
  return [
    `- Evidence: ${observations}`,
    ...snapshot.factorEvidence.slice(0, FACTOR_LINE_COUNT).map((factor) =>
      `  - ${sanitize(factor.displayName)}: ${sanitize(factor.state)} · ${sanitize(factor.effect)} · observed ${sanitize(factor.observedAt)}`),
  ];
}

function riskLabel(brief: StrategyObservationBrief): string {
  if (brief.kind === 'access' || brief.kind === 'pending') return UNVERIFIED_REVIEW_RISK;
  return brief.recovery ? 'Action required' : 'Scheduled cadence';
}

function nextReview(brief: StrategyObservationBrief): string {
  if (brief.kind === 'access' || brief.kind === 'pending') return UNVERIFIED_REVIEW_SCHEDULE;
  return sanitize(brief.nextStep);
}

function fleetCounts(entries: DailyResearchSummaryEntry[]): string {
  const count = (kind: StrategyObservationBrief['kind']) => entries.filter((entry) => entry.brief.kind === kind).length;
  return `${count('changed')} changed · ${count('unchanged')} unchanged · ${count('retained')} retained · `
    + `${count('attention')} need attention · ${count('access')} require access · ${count('pending')} awaiting verification`;
}

function prioritySection(entry: DailyResearchSummaryEntry): string {
  const { run, brief } = entry;
  return [
    `## ${sanitize(run.title)} (${sanitize(run.market.toUpperCase())} · formal evidence through ${sanitize(run.evidenceCutoff)})`,
    `- Observation: ${sanitize(brief.label)}`,
    `- Why: ${sanitize(brief.reason)}`,
    ...evidenceLines(entry),
    `- Risk: ${riskLabel(brief)}`,
    `- Next review: ${nextReview(brief)}`,
  ].join('\n');
}

/**
 * Build the copyable Daily research brief from the already access-filtered
 * entries. It never reads the raw operations map or fields the brief does not render.
 */
export function buildDailyResearchSummary(
  entries: DailyResearchSummaryEntry[],
  options: DailyResearchSummaryOptions,
): string {
  const sections = [[
    `# Daily research summary — ${summaryDate(options.generatedAt)} (UTC)`,
    fleetCounts(entries),
  ].join('\n')];
  for (const entry of entries.slice(0, PRIORITY_COUNT)) sections.push(prioritySection(entry));
  const remaining = entries.slice(PRIORITY_COUNT);
  if (remaining.length) {
    sections.push([
      '## Other formal strategies',
      ...remaining.map((entry) => `- ${sanitize(entry.run.title)}: ${sanitize(entry.brief.label)} `
        + `(formal evidence through ${sanitize(entry.run.evidenceCutoff)})`),
    ].join('\n'));
  }
  sections.push(FOOTER);
  return `${sections.join('\n\n')}\n`;
}
