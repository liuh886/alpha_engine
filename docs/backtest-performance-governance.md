# Backtest performance governance

Alpha Engine exposes two deliberately separate execution paths.  Both remain
`research_only=true` and `trade_ready=false`.

## Four-stage acceleration contract

1. **Dense-array research kernel** — IC, Top-K intent construction, turnover,
   costs and portfolio returns use aligned NumPy arrays.  Stable sorting,
   missing-observation handling and legacy cost semantics remain covered by
   equivalence tests.
2. **Manifest-bound model matrices** — walk-forward features, labels and an
   optional benchmark are stored as non-pickle `.npy` arrays.  A snapshot is
   reused only when its pool, provider bytes, calendar, factor expressions,
   label, benchmark and time boundaries match exactly and every file hash is
   intact.
3. **Bounded training resources** — walk-forward windows may train concurrently
   while sharing the cached matrix through the operating-system file cache.
   The resolver accounts for logical CPUs and available memory, caps per-model
   LightGBM threads and prevents aggregate thread oversubscription.
4. **Dual-engine truth boundary** — `fast_array_research` is interactive,
   non-authoritative diagnostic evidence.  `authoritative_qlib` is the formal
   portfolio-analysis path and writes an execution receipt.  Required
   vectorized precomputation now fails closed; it cannot silently fall back to
   a different engine or reuse a prior run's class-level signals.

## Runtime controls

- `ALPHA_ENGINE_WF_WORKERS`: positive maximum concurrent walk-forward windows.
- `ALPHA_ENGINE_MODEL_THREADS`: positive maximum LightGBM threads per window.
- `walk_forward_vectorized(..., refresh_model_matrix_cache=True)`: force an
  exact cache rebuild.
- `walk_forward_vectorized(..., use_model_matrix_cache=False)`: diagnostic
  opt-out; concurrent split execution is disabled to prevent repeated provider
  scans.

Explicit worker and thread requests are still reduced when their product would
oversubscribe the CPU budget.  Low available memory can reduce the automatic
worker count to one.

## Measured guardrail

On 2026-08-05, the CN130 synthetic equivalence workload (1,400 business days,
Top 15, ten-session rebalance, 20 bps cost) improved from a 3.5263-second
pre-change median to a 0.1685-second post-change median: **20.9x faster**.  The
automated performance guard requires this canonical arithmetic path to remain
below one second.

For a 182,000-row, 50-factor synthetic model matrix, an integrity-checked warm
cache load had a 0.2266-second median.  End-to-end training improvement depends
on provider-expression complexity, factor count, split count and LightGBM
early stopping; those workloads must retain their own run-level timing evidence
instead of extrapolating the arithmetic benchmark.
