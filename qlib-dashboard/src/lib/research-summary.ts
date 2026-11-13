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

/** Collapse line breaks and control whitespace before the Markdown escape step. */
function sanitize(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

// Line-start constructs and inline delimiters that would change the copied
// brief's structure. Adapted from mdast-util-to-markdown lib/unsafe.js (MIT)
// without adding the dependency; only the markers this brief can emit are escaped.
const INLINE_MARKDOWN = /[`[\]]/g;
const LEADING_ORDERED_LIST = /^(\d+)([.)])(?=\s|$)/;
const LEADING_HEADING = /^(#{1,6})(?=\s|$)/;
const LEADING_BULLET = /^-(?=[\s-]|$)|^\+(?=\s|$)/;
const LEADING_BLOCK_QUOTE = /^>/;
const LEADING_SETEXT = /^=/;
const LEADING_TILDE = /^~/;
const LEADING_EMPHASIS = /^[_*]/;

/**
 * Escape a dynamic value so a strategy title or reason cannot open a heading,
 * list, block quote, code span or link in the copied Markdown brief. Normal
 * prose (apostrophes, mid-sentence hyphens, percentages, slashes) is unchanged.
 */
export function escapeMarkdownInline(value: string): string {
  return value
    .replace(INLINE_MARKDOWN, '\\$&')
    .replace(LEADING_ORDERED_LIST, '$1\\$2')
    .replace(LEADING_HEADING, '\\$1')
    .replace(LEADING_BULLET, '\\$&')
    .replace(LEADING_BLOCK_QUOTE, '\\$&')
    .replace(LEADING_SETEXT, '\\$&')
    .replace(LEADING_TILDE, '\\$&')
    .replace(LEADING_EMPHASIS, '\\$&');
}

/** Collapse whitespace, then escape only the dynamic values interpolated into Markdown. */
function dynamicText(value: string): string {
  return escapeMarkdownInline(sanitize(value));
}

function summaryDate(generatedAt: Date): string {
  const date = Number.isNaN(generatedAt.getTime()) ? new Date() : generatedAt;
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

function evidenceLines(entry: DailyResearchSummaryEntry): string[] {
  const { run, snapshot } = entry;
  if (!snapshot) {
    return [`- Evidence: Formal evidence through ${dynamicText(run.evidenceCutoff)}; current observation not verified`];
  }
  const observations = [
    `Observed ${dynamicText(snapshot.latestCompletedSession ?? 'unknown')}`,
    `target dated ${dynamicText(snapshot.decisionSchedule?.signalDate ?? snapshot.asOf ?? 'unknown')}`,
    ...(snapshot.decisionSchedule?.completedThrough
      ? [`completed market through ${dynamicText(snapshot.decisionSchedule.completedThrough)}`]
      : []),
    `formal evidence ${dynamicText(run.evidenceCutoff)}`,
  ].join(' · ');
  return [
    `- Evidence: ${observations}`,
    ...snapshot.factorEvidence.slice(0, FACTOR_LINE_COUNT).map((factor) =>
      `  - ${dynamicText(factor.displayName)}: ${dynamicText(factor.state)} · ${dynamicText(factor.effect)} · observed ${dynamicText(factor.observedAt)}`),
  ];
}

function riskLabel(brief: StrategyObservationBrief): string {
  if (brief.kind === 'access' || brief.kind === 'pending') return UNVERIFIED_REVIEW_RISK;
  return brief.recovery ? 'Action required' : 'Scheduled cadence';
}

function nextReview(brief: StrategyObservationBrief): string {
  if (brief.kind === 'access' || brief.kind === 'pending') return UNVERIFIED_REVIEW_SCHEDULE;
  return dynamicText(brief.nextStep);
}

function fleetCounts(entries: DailyResearchSummaryEntry[]): string {
  const count = (kind: StrategyObservationBrief['kind']) => entries.filter((entry) => entry.brief.kind === kind).length;
  return `${count('changed')} changed · ${count('unchanged')} unchanged · ${count('retained')} retained · `
    + `${count('attention')} need attention · ${count('access')} require access · ${count('pending')} awaiting verification`;
}

function prioritySection(entry: DailyResearchSummaryEntry): string {
  const { run, brief } = entry;
  return [
    `## ${dynamicText(run.title)} (${dynamicText(run.market.toUpperCase())} · formal evidence through ${dynamicText(run.evidenceCutoff)})`,
    `- Observation: ${dynamicText(brief.label)}`,
    `- Why: ${dynamicText(brief.reason)}`,
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
      ...remaining.map((entry) => `- ${dynamicText(entry.run.title)}: ${dynamicText(entry.brief.label)} `
        + `(formal evidence through ${dynamicText(entry.run.evidenceCutoff)})`),
    ].join('\n'));
  }
  sections.push(FOOTER);
  return `${sections.join('\n\n')}\n`;
}
