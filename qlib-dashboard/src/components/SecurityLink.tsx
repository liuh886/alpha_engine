import type { ReactNode } from 'react';
import { securityHref } from '@/lib/security-evidence';

export function SecurityLink({ market, instrument, model, children }: {
  market?: string; instrument: string; model?: string; children?: ReactNode;
}) {
  const href = securityHref(market ?? '', instrument, model);
  return href ? <a href={href} className="font-medium text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary"
    aria-label={`View ${instrument} price and model events`}>{children ?? instrument}</a> : <>{children ?? instrument}</>;
}
