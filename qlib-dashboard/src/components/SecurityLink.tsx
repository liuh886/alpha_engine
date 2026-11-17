import type { ReactNode } from 'react';
import { useSecurityLink } from '@/hooks/useSecurityLink';

const LINK_CLASS = 'font-medium text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary';

/**
 * An instrument cell links only when the market's governed price catalog
 * resolves the symbol. An unresolved alias stays plain text with a short,
 * accessible reason instead of a dead route. The link is always built from the
 * run's own market, so a US model can never link a CN instrument.
 */
export function SecurityLink({ market, instrument, model, children, linkClassName }: {
  market?: string; instrument: string; model?: string; children?: ReactNode; linkClassName?: string;
}) {
  const resolution = useSecurityLink(market, instrument, model);
  const label = children ?? instrument;

  if (resolution.status === 'resolved' && resolution.href) {
    return (
      <a
        href={resolution.href}
        className={`${LINK_CLASS} ${linkClassName ?? ''}`.trim()}
        aria-label={`View ${instrument} price and model events`}
      >
        {label}
      </a>
    );
  }

  return (
    <span
      data-testid="security-link-unresolved"
      data-resolution={resolution.status}
      className="inline-flex min-w-0 flex-wrap items-baseline gap-x-1 font-medium"
      {...(resolution.detail ? { title: resolution.detail } : {})}
    >
      <span>{label}</span>
      {resolution.reason ? (
        <span className="text-[10px] font-normal text-muted-foreground">{resolution.reason}</span>
      ) : null}
    </span>
  );
}
