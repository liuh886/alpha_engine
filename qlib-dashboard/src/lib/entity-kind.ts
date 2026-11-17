/**
 * The four entity kinds the Console can render. `model` is a formal strategy
 * evidence entity; `instrument` is a selected-pool or traded security;
 * `index` and `reference` are governed market context identities.
 *
 * Index/reference classification is derived only from the published
 * market-evidence catalog `roles`. A symbol without a governed index/reference
 * role stays an instrument: the UI never infers an index from a name, a market
 * baseline list or a hard-coded symbol.
 */
export type EntityKind = 'model' | 'instrument' | 'index' | 'reference';

export type EntityMarket = 'us' | 'cn';

export const ENTITY_KIND_LABEL: Readonly<Record<EntityKind, string>> = {
  model: 'Model',
  instrument: 'Instrument',
  index: 'Index',
  reference: 'Reference',
};

export const ENTITY_KIND_ORDER: readonly EntityKind[] = ['model', 'instrument', 'index', 'reference'];

/** Catalog roles that identify governed market context rather than a candidate. */
const INDEX_ROLE = 'benchmark';
const REFERENCE_ROLES = ['formal_auxiliary', 'comparison_reference'] as const;

/**
 * Resolve a security entity's kind from its market-evidence catalog roles.
 * Priority: an explicit `benchmark` role is the market index identity; a
 * governed auxiliary/comparison role is a reference. Everything else is a
 * plain instrument, including a missing role list.
 */
export function entityKindFromRoles(roles: readonly string[] | null | undefined): EntityKind {
  const values = new Set(roles ?? []);
  if (values.has(INDEX_ROLE)) return 'index';
  for (const role of REFERENCE_ROLES) {
    if (values.has(role)) return 'reference';
  }
  return 'instrument';
}

const ROLE_LABEL: Readonly<Record<string, string>> = {
  selected_pool_candidate: 'Selected pool candidate',
  formal_traded: 'Formal traded',
  benchmark: 'Market benchmark',
  formal_auxiliary: 'Formal auxiliary',
  comparison_reference: 'Comparison reference',
};

/** Human-readable catalog roles, in catalog order, without inventing any. */
export function formatEntityRoles(roles: readonly string[] | null | undefined): string {
  const labels = (roles ?? [])
    .map(role => ROLE_LABEL[role] ?? null)
    .filter((label): label is string => label !== null);
  return labels.length > 0 ? labels.join(' · ') : 'Governed instrument';
}
