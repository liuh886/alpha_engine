import { useId, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { ENTITY_KIND_LABEL, type EntityKind, type EntityMarket } from '@/lib/entity-kind';
import { STALE_AFTER_DAYS } from '@/lib/metrics';
import { cn } from '@/lib/utils';

/**
 * The one evidence disclosure used by every entity chart panel. Kind-specific
 * methods stay below in each renderer; this sentence is the shared boundary.
 */
export const ENTITY_CHART_DISCLOSURE = 'Historical research evidence, not a live signal or fill.';

const ENTITY_BOUNDARY = 'Research only · Not trade ready';

export interface EntityIdentity {
  kind: EntityKind;
  /** Heading text. The page owns whether a symbol is joined to the name. */
  name: string;
  /** Canonical id: model_version_id or market instrument identity. */
  entityId: string;
  market: EntityMarket;
  /** Last governed observation date for this entity, when known. */
  asOf: string | null;
  evidenceCutoff: string;
  /** Evidence cutoff minus as-of in calendar days; null when not derivable. */
  staleDays: number | null;
  benchmark?: string | null;
  /** Governed catalog role text, for example "Market benchmark". */
  role?: string | null;
}

export interface EntityBackLink {
  to: string;
  label: string;
}

/**
 * As-of and evidence-cutoff identities are one fact when the dates match and
 * two labelled metrics only when they genuinely differ. Shared by every entity
 * kind so the model and instrument pages cannot drift.
 */
export function EntityDateFacts({
  asOf,
  cutoff,
  testIdPrefix = 'entity',
}: {
  asOf: string | null;
  cutoff: string;
  testIdPrefix?: string;
}) {
  if (asOf !== null && asOf === cutoff) {
    return (
      <div>
        <dt className="ae-metric-label">As of · evidence cutoff</dt>
        <dd data-testid={`${testIdPrefix}-as-of-cutoff`} className="mt-1 font-mono text-sm font-semibold tabular-nums">
          {cutoff}
        </dd>
      </div>
    );
  }
  return (
    <>
      <div>
        <dt className="ae-metric-label">As of</dt>
        <dd data-testid={`${testIdPrefix}-as-of`} className="mt-1 font-mono text-sm font-semibold tabular-nums">
          {asOf ?? '—'}
        </dd>
      </div>
      <div>
        <dt className="ae-metric-label">Evidence cutoff</dt>
        <dd data-testid={`${testIdPrefix}-evidence-cutoff`} className="mt-1 font-mono text-sm font-semibold tabular-nums">
          {cutoff}
        </dd>
      </div>
    </>
  );
}

export interface EntityHeaderProps {
  identity: EntityIdentity;
  back: EntityBackLink;
  kicker?: string;
  description?: ReactNode;
  /** Extra status chips such as an access tier. */
  chips?: ReactNode;
  /** Right-hand metric column, for example last close or operating status. */
  metrics?: ReactNode;
}

/**
 * One header pattern for model, instrument, index and reference pages:
 * a consistent back link, kind badge, market, display name, canonical id,
 * as-of/evidence-cutoff facts, stale chip, benchmark, role and boundary.
 */
export function EntityHeader({
  identity,
  back,
  kicker,
  description,
  chips,
  metrics,
}: EntityHeaderProps) {
  const { kind, name, entityId, market, asOf, evidenceCutoff, staleDays, benchmark, role } = identity;
  const stale = typeof staleDays === 'number' && staleDays > STALE_AFTER_DAYS;
  const showEntityId = entityId !== name && !name.includes(entityId);
  return (
    <div className="space-y-4">
      <Link
        to={back.to}
        className="inline-flex min-h-10 items-center gap-2 text-sm text-primary"
        data-testid="entity-back"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        {back.label}
      </Link>
      <header className="research-page-header" data-testid="entity-header" data-entity-kind={kind}>
        <div className="min-w-0">
          <p className="research-kicker">{kicker ?? `${market.toUpperCase()} · Historical research evidence`}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <Badge variant="secondary" data-testid="entity-kind-badge">{ENTITY_KIND_LABEL[kind]}</Badge>
            <span className="ae-chip">{market.toUpperCase()}</span>
            {chips}
          </div>
          <h1 className="mt-2" data-testid="entity-title">{name}</h1>
          {showEntityId && (
            <p data-testid="entity-id" className="mt-1 break-all font-mono text-[11px] leading-4 text-muted-foreground">
              {entityId}
            </p>
          )}
          {description ? (
            <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p>
          ) : null}
          <dl data-testid="entity-facts" className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2">
            <EntityDateFacts asOf={asOf} cutoff={evidenceCutoff} />
            {benchmark ? (
              <div>
                <dt className="ae-metric-label">Benchmark</dt>
                <dd className="mt-1 font-mono text-sm font-semibold">{benchmark}</dd>
              </div>
            ) : null}
            {role ? (
              <div>
                <dt className="ae-metric-label">Role</dt>
                <dd className="mt-1 text-sm font-semibold">{role}</dd>
              </div>
            ) : null}
            <div>
              <dt className="ae-metric-label">Boundary</dt>
              <dd className="mt-1 text-sm font-semibold">{ENTITY_BOUNDARY}</dd>
            </div>
            {stale ? (
              <div>
                <dt className="ae-metric-label">Freshness</dt>
                <dd className="mt-1">
                  <span
                    data-testid="entity-stale"
                    className="rounded bg-warning/10 px-1.5 py-0.5 text-[11px] font-semibold text-warning"
                  >
                    Stale · {staleDays}d behind cutoff
                  </span>
                </dd>
              </div>
            ) : null}
          </dl>
        </div>
        {metrics ? <div className="shrink-0">{metrics}</div> : null}
      </header>
    </div>
  );
}

export interface EntityChartPanelProps {
  testId: string;
  title: string;
  description?: ReactNode;
  /** Existing period/baseline/indicator/compare controls for this renderer. */
  controls?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** Accessible region name; when omitted the panel is named by its heading. */
  ariaLabel?: string;
  /** Preserves the instrument page's marker-count contract on the section. */
  dataMarkerCount?: number;
  disclosure?: string;
}

/**
 * The one chart panel frame. Renderers stay separate (NAV vs OHLCV); this shell
 * owns the heading, control row, disclosure language and surface spacing.
 */
export function EntityChartPanel({
  testId,
  title,
  description,
  controls,
  children,
  className,
  bodyClassName,
  ariaLabel,
  dataMarkerCount,
  disclosure = ENTITY_CHART_DISCLOSURE,
}: EntityChartPanelProps) {
  const headingId = useId();
  return (
    <section
      data-testid={testId}
      {...(ariaLabel ? { 'aria-label': ariaLabel } : { 'aria-labelledby': headingId })}
      {...(typeof dataMarkerCount === 'number' ? { 'data-marker-count': dataMarkerCount } : {})}
      className={cn('research-surface flex flex-col overflow-hidden', className)}
    >
      <header className="order-1 flex flex-col gap-3 border-b p-4 sm:p-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h2 id={headingId} className="ae-section-title">{title}</h2>
          {description}
          <p data-testid="entity-chart-disclosure" className="mt-1 text-[11px] leading-4 text-muted-foreground">
            {disclosure}
          </p>
        </div>
        {controls ? <div className="flex flex-wrap items-center gap-2">{controls}</div> : null}
      </header>
      <div className={cn('flex min-h-0 flex-1 flex-col', bodyClassName)}>{children}</div>
    </section>
  );
}

/**
 * Composition slot for each kind's existing evidence sections. It adds no
 * section of its own: model metrics/holdings/trades/attribution, instrument
 * price/event/binding sections and index/reference role context stay owned by
 * their pages.
 */
export function EntityEvidenceSections({
  children,
  label = 'Entity evidence',
}: {
  children: ReactNode;
  label?: string;
}) {
  return (
    <div data-testid="entity-evidence-sections" aria-label={label} className="space-y-5">
      {children}
    </div>
  );
}

export type RelatedEntityRelation = 'held_by' | 'traded_by' | 'holds' | 'traded_in';

/**
 * Phase 3 reserved link contract. Lists, cards and markers will resolve these
 * through the shared entity resolver; no page populates them yet.
 */
export interface RelatedEntityLink {
  relation: RelatedEntityRelation;
  kind: EntityKind;
  market: EntityMarket;
  entityId: string;
  label: string;
  /** Canonical in-app route, for example `#/securities/us/AAPL`. */
  href: string;
}

const RELATION_LABEL: Readonly<Record<RelatedEntityRelation, string>> = {
  held_by: 'Held by',
  traded_by: 'Traded by',
  holds: 'Holds',
  traded_in: 'Traded in',
};

/**
 * Typed Phase 3 slot. With no links it renders nothing, so Phase 2 pages keep
 * their current evidence surface without a placeholder promise.
 */
export function EntityRelatedEntities({
  links = [],
  title = 'Related entities',
}: {
  links?: readonly RelatedEntityLink[];
  title?: string;
}) {
  if (links.length === 0) return null;
  return (
    <section data-testid="entity-related" aria-label={title} className="research-surface p-4 sm:p-5">
      <h2 className="ae-section-title">{title}</h2>
      <ul className="mt-3 divide-y">
        {links.map(link => (
          <li key={`${link.relation}:${link.kind}:${link.entityId}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2 text-sm">
            <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              {RELATION_LABEL[link.relation]}
            </span>
            <a href={link.href} className="font-medium text-primary underline decoration-primary/30 underline-offset-4">
              {link.label}
            </a>
            <span className="font-mono text-[10px] text-muted-foreground">
              {ENTITY_KIND_LABEL[link.kind]} · {link.market.toUpperCase()} · {link.entityId}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export interface EntityWorkspaceProps extends EntityHeaderProps {
  children: ReactNode;
  /** Phase 3 links; empty by default in Phase 2. */
  related?: readonly RelatedEntityLink[];
}

/**
 * One detail shell shared by model, instrument, index and reference pages.
 * Pages provide their chart panel and evidence sections; the shell owns the
 * header, page width/spacing and the reserved related-entity slot.
 */
export function EntityWorkspace({ children, related, ...header }: EntityWorkspaceProps) {
  return (
    <div
      className="research-page space-y-5 pb-16"
      data-testid="entity-workspace"
      data-entity-kind={header.identity.kind}
    >
      <EntityHeader {...header} />
      {children}
      <EntityRelatedEntities links={related} />
    </div>
  );
}
