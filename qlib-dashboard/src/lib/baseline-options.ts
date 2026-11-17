import type { BaselineKind, BaselineMarket, BaselineOption, BaselineRunIdentity } from './baseline';
import { defaultSecurityBaselineKind, securityBaselineOptions } from './security-baseline';
import { defaultBaselineKind, strategyBaselineOptions } from './strategy-chart';
import type { ReportRow } from './types';

/**
 * One typed option source for the shared `BaselineControl`. The strategy view
 * reads declared benchmark wealth plus the governed market series; the security
 * view offers only the governed market series and never invents a model
 * benchmark from price evidence.
 */
export type BaselineOptionSource =
  | { view: 'strategy'; run: BaselineRunIdentity; rows: ReportRow[] }
  | { view: 'security'; market: BaselineMarket; isSelf: boolean };

export function baselineOptionsFor(source: BaselineOptionSource): BaselineOption[] {
  return source.view === 'strategy'
    ? strategyBaselineOptions(source.run, source.rows)
    : securityBaselineOptions(source.market, { isSelf: source.isSelf });
}

/**
 * Resolve the initial selection for the same source. Strategy keeps its
 * existing declared-or-none default; a security opens in price mode unless the
 * viewer explicitly chose the market baseline.
 */
export function defaultBaselineKindFor(
  source: BaselineOptionSource,
  options: readonly BaselineOption[],
  preferred: BaselineKind,
): BaselineKind {
  return source.view === 'strategy'
    ? defaultBaselineKind(options, preferred)
    : defaultSecurityBaselineKind(options, preferred);
}
