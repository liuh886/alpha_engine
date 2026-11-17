import { Link } from 'react-router-dom';
import { formatMarkerWeight } from '@/lib/chart-markers';
import type { RelatedModelEntry, RelatedHoldingState } from '@/lib/related-entities';
import { formatEventAction } from '@/lib/security-format';

function eventText(entry: RelatedModelEntry): string {
  if (!entry.events) return 'No retained trade events';
  const { eventCount, lastAction, lastEventDate } = entry.events;
  return `${eventCount} retained event${eventCount === 1 ? '' : 's'} · last ${formatEventAction(lastAction)} on ${lastEventDate}`;
}

function holdingText(holding: RelatedHoldingState): { text: string; tone: 'held' | 'muted' | 'warning' } {
  if (holding.status === 'held') {
    return {
      text: `Held at last publication · ${formatMarkerWeight(holding.weight)} · as of ${holding.asOf} · cutoff ${holding.cutoff}`,
      tone: 'held',
    };
  }
  if (holding.status === 'not_held') {
    return {
      text: `Not held at last publication · portfolio as of ${holding.asOf} · cutoff ${holding.cutoff}`,
      tone: 'muted',
    };
  }
  if (holding.status === 'unavailable') {
    return { text: `Latest holdings unavailable · ${holding.reason}`, tone: 'warning' };
  }
  return { text: 'Reading latest published holdings…', tone: 'muted' };
}

const TONE_CLASS: Record<'held' | 'muted' | 'warning', string> = {
  held: 'text-positive',
  muted: 'text-muted-foreground',
  warning: 'text-warning',
};

/**
 * The Phase 3 instrument → model relation panel inside the shared entity
 * shell. It renders nothing when no accepted formal model traded or held the
 * instrument, so plain instruments keep only their own evidence sections.
 */
export function RelatedModelsPanel({
  entries,
  title = 'Related models',
}: {
  entries: readonly RelatedModelEntry[];
  title?: string;
}) {
  if (entries.length === 0) return null;
  return (
    <section data-testid="related-models" aria-label={title} className="research-surface p-4 sm:p-5">
      <h2 className="ae-section-title">{title}</h2>
      <p className="mt-1 max-w-3xl text-[11px] leading-4 text-muted-foreground">
        Accepted formal models bound to this market's published evidence. Event counts come only from exact bound
        ledger rows; holdings come from each run's latest published portfolio section and are never inferred from
        event weights.
      </p>
      <ul className="mt-3 divide-y">
        {entries.map((entry) => {
          const holding = holdingText(entry.holding);
          return (
            <li
              key={entry.modelVersionId}
              data-testid="related-model"
              data-model-id={entry.modelVersionId}
              className="flex flex-col gap-1 py-3 sm:flex-row sm:flex-wrap sm:items-baseline sm:gap-x-4"
            >
              <Link
                to={`/strategies/${encodeURIComponent(entry.modelVersionId)}`}
                className="research-touch inline-flex min-h-11 items-center font-medium text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                {entry.title}
              </Link>
              <span data-testid="related-model-events" className="text-sm text-muted-foreground">
                {eventText(entry)}
              </span>
              <span
                data-testid="related-model-holding"
                data-holding-status={entry.holding.status}
                className={`text-[11px] leading-4 ${TONE_CLASS[holding.tone]}`}
              >
                {holding.text}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
