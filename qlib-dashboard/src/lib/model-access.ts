import type { GovernedRunSummary } from './governed-run';

export const ALPHA_PRO_ENTITLEMENT = 'alpha_engine.pro';
export const PRO_MODEL_FAMILIES = new Set(['qqq_rotation']);

export function isProModelRun(run: GovernedRunSummary | null | undefined): boolean {
  return Boolean(run && PRO_MODEL_FAMILIES.has(run.modelFamilyId));
}
