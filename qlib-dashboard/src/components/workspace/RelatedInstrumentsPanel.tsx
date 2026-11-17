import { useEffect, useState } from 'react';
import { SecurityLink } from '@/components/SecurityLink';
import {
  readRelatedTradeInstruments,
  type RelatedTradeInstrumentsRead,
} from '@/lib/related-entities';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { formatEventAction } from '@/lib/security-format';

type PanelState = { status: 'loading' } | RelatedTradeInstrumentsRead;

/**
 * Always-mounted model→instrument relation in the shared entity shell. It reads
 * the retained formal trade ledger (never holdings) and links each instrument
 * through the model's own market catalog. This gives the model→instrument
 * journey a discoverable entry point before any evidence tab is opened.
 */
export function RelatedInstrumentsPanel({ run }: { run: GovernedRunSummary }) {
  const [state, setState] = useState<PanelState>({ status: 'loading' });

  useEffect(() => {
    let active = true;
    setState({ status: 'loading' });
    void readRelatedTradeInstruments(run).then(result => {
      if (active) setState(result);
    });
    return () => { active = false; };
  }, [run]);

  if (state.status === 'loading') return null;

  if (state.status === 'unavailable') {
    return (
      <section data-testid="related-instruments" aria-label="Related instruments" className="research-surface p-4 sm:p-5">
        <h2 className="ae-section-title">Related instruments</h2>
        <p className="mt-2 text-sm text-warning">Retained trade ledger unavailable · {state.reason}</p>
        <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
          No instrument links are offered without the verified ledger. Nothing is inferred from current weights or
          another market's catalog.
        </p>
      </section>
    );
  }

  if (state.instruments.length === 0) return null;

  return (
    <section data-testid="related-instruments" aria-label="Related instruments" className="research-surface p-4 sm:p-5">
      <h2 className="ae-section-title">Related instruments</h2>
      <p className="mt-1 max-w-3xl text-[11px] leading-4 text-muted-foreground">
        Instruments in this model's retained formal trade ledger, by latest action. Links resolve through this model's
        own market price evidence; an unresolved instrument stays plain text with a reason. These are trade-ledger
        facts, not inferred holdings.
      </p>
      <ul className="mt-3 divide-y">
        {state.instruments.map((row) => (
          <li
            key={row.instrument}
            data-testid="related-instrument"
            data-instrument={row.instrument}
            className="flex flex-col gap-1 py-3 sm:flex-row sm:flex-wrap sm:items-baseline sm:gap-x-4"
          >
            <SecurityLink
              market={run.market}
              model={run.modelVersionId}
              instrument={row.instrument}
              linkClassName="research-touch inline-flex min-h-11 items-center"
            >
              {row.instrument}
            </SecurityLink>
            <span data-testid="related-instrument-trades" className="text-sm text-muted-foreground">
              {row.tradeCount} retained trade{row.tradeCount === 1 ? '' : 's'} · last {formatEventAction(row.lastAction)} on {row.lastDate}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
