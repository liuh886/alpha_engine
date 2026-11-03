import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  fetchStudyReviews,
  type CounterEvidenceItem,
  type ReviewLifecycleState,
  type StudyReview,
} from '@/lib/study-review';

const stateLabels: Record<ReviewLifecycleState, { label: string; badgeClass: string }> = {
  formulated: { label: 'Formulated', badgeClass: 'bg-muted text-muted-foreground' },
  observing: { label: 'Observing', badgeClass: 'bg-blue-500/10 text-blue-700 dark:text-blue-400 border-blue-500/30' },
  supported: { label: 'Supported', badgeClass: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/30' },
  challenged: { label: 'Challenged', badgeClass: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/30' },
  refuted: { label: 'Refuted', badgeClass: 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/30' },
  graduated: { label: 'Graduated', badgeClass: 'bg-purple-500/10 text-purple-700 dark:text-purple-400 border-purple-500/30' },
};

function formatPct(val: number | undefined | null): string {
  if (val === undefined || val === null || Number.isNaN(val)) return 'n/a';
  const pct = val * 100;
  return `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`;
}

interface ReviewModalProps {
  review: StudyReview;
  onClose: () => void;
}

function ReviewModal({ review, onClose }: ReviewModalProps) {
  const stateInfo = stateLabels[review.lifecycle_state] ?? { label: review.lifecycle_state, badgeClass: 'bg-muted text-muted-foreground' };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="review-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4 overflow-y-auto"
    >
      <div className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-xl border bg-card p-6 shadow-xl space-y-6">
        <div className="flex items-start justify-between border-b pb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className={`inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold ${stateInfo.badgeClass}`}>
                {stateInfo.label}
              </span>
              <span className="text-xs text-muted-foreground font-mono">{review.review_id}</span>
            </div>
            <h2 id="review-modal-title" className="mt-2 text-xl font-bold tracking-tight">
              {review.title}
            </h2>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close dialog">
            ✕
          </Button>
        </div>

        {/* Stage 1: Hypothesis Formulation */}
        <section className="space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
            <span>1. Hypothesis Formulation</span>
          </h3>
          <div className="rounded-lg border bg-muted/20 p-4 space-y-2">
            <p className="text-sm font-medium">{review.hypothesis.statement}</p>
            <div className="grid gap-2 sm:grid-cols-2 text-xs text-muted-foreground pt-2 border-t">
              <div>
                <span className="font-semibold text-foreground">Rationale: </span>
                {review.hypothesis.economic_rationale}
              </div>
              <div>
                <span className="font-semibold text-foreground">Expected Edge: </span>
                {review.hypothesis.expected_edge}
              </div>
            </div>
            {review.hypothesis.falsification_criteria.length > 0 && (
              <div className="pt-2 text-xs">
                <span className="font-semibold text-rose-600 dark:text-rose-400">Falsification Criteria:</span>
                <ul className="list-disc list-inside mt-1 space-y-0.5 text-muted-foreground">
                  {review.hypothesis.falsification_criteria.map((c, idx) => (
                    <li key={idx}>{c}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>

        {/* Stage 2: Frozen Conditions */}
        <section className="space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            2. Frozen Conditions
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="rounded-lg border p-3 bg-card">
              <span className="text-muted-foreground block">Frozen Cutoff</span>
              <span className="font-mono font-medium">{review.frozen_conditions.frozen_at_cutoff}</span>
            </div>
            <div className="rounded-lg border p-3 bg-card">
              <span className="text-muted-foreground block">Universe / Pool</span>
              <span className="font-mono font-medium">{review.frozen_conditions.pool_id}</span>
            </div>
            <div className="rounded-lg border p-3 bg-card">
              <span className="text-muted-foreground block">Friction Model</span>
              <span className="font-mono font-medium">{review.frozen_conditions.cost_bps} bps</span>
            </div>
            <div className="rounded-lg border p-3 bg-card">
              <span className="text-muted-foreground block">Cadence</span>
              <span className="font-mono font-medium">{review.frozen_conditions.rebalance_cadence}</span>
            </div>
          </div>
        </section>

        {/* Stage 3: Performance Observations */}
        <section className="space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            3. Performance Observations
          </h3>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-left text-xs">
              <thead className="bg-muted/40 font-medium text-muted-foreground border-b">
                <tr>
                  <th className="p-3">Scope</th>
                  <th className="p-3">As of</th>
                  <th className="p-3">Cumulative</th>
                  <th className="p-3">Sharpe</th>
                  <th className="p-3">Max DD</th>
                  <th className="p-3">vs Pool EW</th>
                  <th className="p-3">vs QQQ</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {Object.entries(review.observations).map(([key, obs]) => (
                  <tr key={key} className="hover:bg-muted/20 font-mono">
                    <td className="p-3 font-sans font-medium">{key}</td>
                    <td className="p-3">{obs.as_of_session}</td>
                    <td className="p-3">{formatPct(obs.cumulative_return)}</td>
                    <td className="p-3">{obs.sharpe_ratio.toFixed(2)}</td>
                    <td className="p-3 text-rose-600 dark:text-rose-400">{formatPct(obs.max_drawdown)}</td>
                    <td className="p-3">{formatPct(obs.vs_benchmark_returns.us87_ew_pool_runner_v1)}</td>
                    <td className="p-3">{formatPct(obs.vs_benchmark_returns.QQQ)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Stage 4: Counter-Evidence Collection */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              4. Counter-Evidence Collection
            </h3>
            <span className="text-xs text-muted-foreground">
              {review.counter_evidence.length} items logged
            </span>
          </div>
          {review.counter_evidence.length === 0 ? (
            <p className="text-xs text-muted-foreground italic">No counter-evidence observed to date.</p>
          ) : (
            <div className="space-y-2">
              {review.counter_evidence.map((ce: CounterEvidenceItem) => (
                <div key={ce.evidence_id} className="rounded-lg border p-3 text-xs space-y-1">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold">{ce.evidence_id}</span>
                      <span className="text-muted-foreground">({ce.session})</span>
                      <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium">{ce.category}</span>
                    </div>
                    <span
                      className={`font-semibold uppercase text-[10px] ${
                        ce.severity === 'falsifying'
                          ? 'text-rose-600 dark:text-rose-400'
                          : ce.severity === 'warning'
                          ? 'text-amber-600 dark:text-amber-400'
                          : 'text-muted-foreground'
                      }`}
                    >
                      {ce.severity}
                    </span>
                  </div>
                  <p className="text-muted-foreground">{ce.observation}</p>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Stage 5: Review Conclusion */}
        <section className="space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            5. Review Conclusion
          </h3>
          <div className="rounded-lg border bg-muted/10 p-4 space-y-2 text-xs">
            <div className="flex items-center justify-between border-b pb-2">
              <span className="font-semibold text-sm">{review.conclusion.verdict}</span>
              <span className="text-muted-foreground">Session: {review.conclusion.verdict_session}</span>
            </div>
            <p className="text-muted-foreground">{review.conclusion.summary}</p>
            {review.conclusion.supported_points.length > 0 && (
              <div className="pt-2">
                <span className="font-medium text-emerald-600 dark:text-emerald-400">Supported Points:</span>
                <ul className="list-disc list-inside mt-0.5 space-y-0.5 text-muted-foreground">
                  {review.conclusion.supported_points.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </div>
            )}
            {review.conclusion.unresolved_risks.length > 0 && (
              <div className="pt-2">
                <span className="font-medium text-amber-600 dark:text-amber-400">Unresolved Risks:</span>
                <ul className="list-disc list-inside mt-0.5 space-y-0.5 text-muted-foreground">
                  {review.conclusion.unresolved_risks.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="pt-2 text-right">
              <span className="text-muted-foreground">Recommendation: </span>
              <span className="font-mono font-semibold">{review.conclusion.recommendation}</span>
            </div>
          </div>
        </section>

        {/* Stage 6: Scheduled Review & Watchpoints */}
        <section className="space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            6. Scheduled Review & Watchpoints
          </h3>
          <div className="grid sm:grid-cols-2 gap-3 text-xs">
            <div className="rounded-lg border p-3">
              <span className="text-muted-foreground block">Next Scheduled Review</span>
              <span className="font-mono font-bold text-sm text-primary">{review.scheduled_review.next_review_session}</span>
              <span className="text-muted-foreground block mt-1">Cadence: {review.scheduled_review.cadence}</span>
            </div>
            <div className="rounded-lg border p-3">
              <span className="text-muted-foreground block font-medium">Automatic Breach Triggers</span>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-muted-foreground">
                {review.scheduled_review.review_triggers.map((t, idx) => (
                  <li key={idx}>⚡ {t}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <div className="flex justify-end pt-4 border-t">
          <Button onClick={onClose}>Close Review</Button>
        </div>
      </div>
    </div>
  );
}

export function StudyReviewDesk({ attempt = 0 }: { attempt?: number }) {
  const [reviews, setReviews] = useState<StudyReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterState, setFilterState] = useState<string>('all');
  const [activeReview, setActiveReview] = useState<StudyReview | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    fetchStudyReviews(controller.signal)
      .then((feed) => {
        setReviews(feed.reviews);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'Failed to load study reviews');
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [attempt]);

  const filteredReviews = reviews.filter((r) =>
    filterState === 'all' ? true : r.lifecycle_state === filterState
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-4">
        <div>
          <h2 className="text-lg font-bold tracking-tight">Hypothesis Review Desk</h2>
          <p className="text-xs text-muted-foreground mt-1">
            Empirical lifecycle of frozen quantitative hypotheses: tracking out-of-sample edge, cataloging counter-evidence, and scheduling review checkpoints.
          </p>
        </div>
        <div className="flex items-center gap-1.5 overflow-x-auto text-xs" aria-label="Filter reviews by state">
          {['all', 'observing', 'supported', 'challenged', 'refuted', 'graduated'].map((st) => (
            <button
              key={st}
              type="button"
              onClick={() => setFilterState(st)}
              className={`rounded-md px-2.5 py-1 font-medium capitalize transition-colors ${
                filterState === st
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted/60 text-muted-foreground hover:bg-muted'
              }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {loading && <p role="status" className="text-sm text-muted-foreground">Loading study reviews…</p>}

      {error && (
        <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <p className="font-semibold">Unable to load study reviews</p>
          <p className="text-xs mt-1 text-muted-foreground">{error}</p>
        </div>
      )}

      {!loading && !error && filteredReviews.length === 0 && (
        <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
          No investment hypotheses currently in {filterState === 'all' ? 'any' : filterState} state.
        </div>
      )}

      {!loading && !error && filteredReviews.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filteredReviews.map((rev) => {
            const stateInfo = stateLabels[rev.lifecycle_state] ?? {
              label: rev.lifecycle_state,
              badgeClass: 'bg-muted text-muted-foreground',
            };
            const primaryObs = rev.observations.full_sample_2024_2026 ?? Object.values(rev.observations)[0];
            const warningCount = rev.counter_evidence.filter((c) => c.severity === 'warning' || c.severity === 'falsifying').length;

            return (
              <div
                key={rev.review_id}
                className="flex flex-col justify-between rounded-xl border bg-card p-5 shadow-sm space-y-4 hover:border-primary/50 transition-colors"
              >
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold ${stateInfo.badgeClass}`}>
                      {stateInfo.label}
                    </span>
                    <span className="text-[11px] font-mono text-muted-foreground">{rev.frozen_conditions.runner_id}</span>
                  </div>

                  <h3 className="font-bold text-base tracking-tight leading-snug">{rev.title}</h3>

                  <p className="text-xs text-muted-foreground line-clamp-3 leading-relaxed">
                    {rev.hypothesis.statement}
                  </p>

                  {primaryObs && (
                    <div className="grid grid-cols-3 gap-2 rounded-lg bg-muted/20 p-2.5 text-center text-xs border">
                      <div>
                        <span className="text-[10px] text-muted-foreground block">Return</span>
                        <span className="font-mono font-medium">{formatPct(primaryObs.cumulative_return)}</span>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted-foreground block">Max DD</span>
                        <span className="font-mono font-medium text-rose-600 dark:text-rose-400">
                          {formatPct(primaryObs.max_drawdown)}
                        </span>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted-foreground block">Sharpe</span>
                        <span className="font-mono font-medium">{primaryObs.sharpe_ratio.toFixed(2)}</span>
                      </div>
                    </div>
                  )}

                  <div className="flex items-center justify-between text-[11px] text-muted-foreground pt-1">
                    <span>
                      Counter-evidence:{' '}
                      <strong className={warningCount > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-foreground'}>
                        {rev.counter_evidence.length}
                      </strong>
                    </span>
                    <span>Next: <strong className="text-foreground">{rev.scheduled_review.next_review_session}</strong></span>
                  </div>
                </div>

                <Button variant="outline" size="sm" className="w-full mt-2" onClick={() => setActiveReview(rev)}>
                  Inspect Full Review
                </Button>
              </div>
            );
          })}
        </div>
      )}

      {activeReview && (
        <ReviewModal review={activeReview} onClose={() => setActiveReview(null)} />
      )}
    </div>
  );
}
