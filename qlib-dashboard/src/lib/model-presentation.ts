export const QQQR_DISPLAY_NAME = 'QQQR';

interface ModelPresentationIdentity {
  modelFamilyId?: string | null;
  modelVersionId?: string | null;
  modelId?: string | null;
}

const PUBLIC_DISPLAY_NAME_BY_MODEL_ID: Record<string, string> = {
  byd_dividend_sleeve_v1_0: 'BYD v1.1',
};

function isQqqRotation(identity: ModelPresentationIdentity): boolean {
  if (identity.modelFamilyId === 'qqq_rotation') return true;
  return [identity.modelVersionId, identity.modelId]
    .filter((value): value is string => typeof value === 'string')
    .some((value) => value.startsWith('qqqi_qqq_tqqq_'));
}

/**
 * Maps immutable model identities to concise public names without rewriting
 * hash-bound research artifacts or changing routes, cache keys, or run IDs.
 */
export function publicModelDisplayName(
  fallback: string,
  identity: ModelPresentationIdentity,
): string {
  if (isQqqRotation(identity)) return QQQR_DISPLAY_NAME;
  if (identity.modelId && PUBLIC_DISPLAY_NAME_BY_MODEL_ID[identity.modelId]) {
    return PUBLIC_DISPLAY_NAME_BY_MODEL_ID[identity.modelId];
  }
  return fallback;
}
