# Data Coverage Alignment

## Purpose

The `market_data_alignment` module implements **Route B**: automatic train-start
alignment that preserves strict fail-closed defaults while allowing the system to
discover the earliest date at which sufficient symbol coverage is available.

## Problem

When a research pipeline requests `train_start = "2021-01-01"` but several
symbols were only listed in April 2021, a strict coverage check drops those
symbols. If too few remain, the entire market/universe is skipped — even though
a slightly later start (e.g. `2021-04-06`) would retain enough symbols.

## Solution

**`--alignment-mode auto`** finds the earliest common date at which ≥
*min_symbols* symbols have valid data through *test_end*. The aligned start is
**always ≥ the requested start** — it never shifts earlier, forward-fills, or
zero-fills missing data.

## Modes

### `strict` (default)

The requested `train_start` is used unchanged. If fewer than *min_symbols*
symbols have coverage spanning the requested range, the result is **skipped**
with a reason. This is the safe default.

### `auto`

The system attempts to find a later `train_start` that retains ≥ *min_symbols*
symbols:

1. Collect per-symbol `first_valid_date` / `last_valid_date` from Qlib `$close`
   data (via `load_symbol_date_coverage`).
2. Drop symbols whose `first_valid_date` is `None` or whose `last_valid_date` is
   before `test_end`.
3. Sort remaining symbols by `first_valid_date` ascending.
4. Take the *min_symbols*-th symbol's `first_valid_date` as the candidate
   aligned start.
5. If the candidate > requested start, adopt it; otherwise keep the requested
   start.
6. Re-filter: drop symbols whose `first_valid_date` > aligned start.
7. Verify ≥ 3 half-year OOS windows can form from the aligned start through the
   2024–2026 validation range. If not, skip.

## Key Functions

| Function | Purpose |
|---|---|
| `find_common_coverage_start(symbol_dates, min_symbols, test_end)` | Find earliest date with ≥ min_symbols qualified symbols |
| `align_train_start_to_coverage(spec, date_coverage, alignment_mode)` | Align one market spec |
| `build_aligned_market_readiness(specs, alignment_mode)` | Align multiple markets at once |

## Output Fields (`CoverageAlignment`)

| Field | Type | Description |
|---|---|---|
| `alignment_mode` | `str` | `"strict"` or `"auto"` |
| `market` | `str` | Market identifier (e.g. `"us"`, `"cn"`) |
| `requested_train_start` | `str` | Original requested train-start (YYYY-MM-DD) |
| `aligned_train_start` | `str` | Train-start after alignment (always ≥ requested) |
| `alignment_reason` | `str` | Why the decision was made — `"strict unchanged"`, `"auto shifted"`, `"auto unchanged"`, or `"skipped: …"` |
| `retained_symbols` | `tuple[str]` | Symbols with valid coverage (empty when skipped) |
| `dropped_symbols` | `tuple[str]` | Symbols excluded from retained set |
| `drop_reasons` | `dict[str, str]` | Per-symbol reason for every dropped symbol |
| `min_symbols` | `int` | Minimum symbol count gate |
| `test_end` | `str` | Test-end boundary |
| `sufficient` | `bool` | `True` when retained ≥ min_symbols AND ≥ 3 OOS windows |
| `skipped` | `bool` | `True` when fail-closed (convenience negation) |
| `skip_reason` | `str \| None` | Human-readable reason when skipped |
| `viable_windows` | `int` | Count of half-year OOS windows surviving alignment |
| `min_viable_windows` | `int` | Required minimum (default 3) |

> **Note:** Legacy keys `requested_start` and `aligned_start` are available as
> read-only property aliases on the dataclass and are included in `to_dict()`
> for backward compatibility. New code should prefer the canonical names.

## Integration Points

### `scripts/check_multi_market_data_readiness.py`

Runs both US and CN markets through alignment. With `--alignment-mode auto`,
each market independently discovers its optimal start.

### `scripts/run_cn_10d_validation.py`

When auto alignment passes, uses the aligned `train_start` for rolling window
generation. When it fails, writes `cn_validation_skipped.json` with the reason
and alignment details.

### `scripts/run_best_blend_universe_robustness.py`

Applies per-universe aligned `train_start` in auto mode. Each of the three
universe specs (default_10, expanded_50, expanded_100) gets independent
alignment. The frozen #86 candidates are used unchanged; only the train-start
shifts.

## Fail-Closed Guarantees

1. **Never forward-fill**: Symbols without `first_valid_date` are dropped, not
   imputed.
2. **Never zero-fill**: Zero-observation symbols are treated as missing.
3. **Never leak**: When `skipped = True`, `retained_symbols` is always empty
   (`[]`).
4. **Min-symbols gate**: Fewer than *min_symbols* retained → skipped.
5. **Min-windows gate**: Fewer than 3 half-year OOS windows viable → skipped.
6. **CN leading zeros**: Six-digit CN codes (e.g. `000001`) pass through
   unchanged.

## Validation Results (2026-07-07)

### Strict Mode

| Market | Requested | Full-Range / Sufficient | Retained | Skipped |
|--------|-----------|------------------------|----------|---------|
| US     | 137       | 7                      | 0        | True    |
| CN     | 233       | 1                      | 0        | True    |

### Auto Alignment

| Market | Aligned Start | Retained | Viable Windows | Readiness |
|--------|---------------|----------|----------------|-----------|
| US     | 2021-04-05    | 121      | 4              | Pass      |
| CN     | 2021-04-06    | 203      | 4              | Pass      |

Both markets pass the minimum-coverage gate after auto alignment.

### US Universe Validation

- **`default_10`**: Evaluated. Fixed blend mean ICIR **0.26814**, worst drawdown **-0.09555**, ready_ratio **0.50**.
  - Blocker: mean ICIR < 0.30, ready_ratio < 0.75.
  - Decision: **`stronger_research_candidate`**, trade_ready **false**.
- **`expanded_50`**: Skipped (49/50 symbols).
- **`expanded_100`**: Skipped (98/100 symbols).

### CN 10D Validation

- **4 windows** generated after auto alignment.
- All candidates fail the stable threshold.
- Highest mean ICIR row: ranker original **0.09593**, worst drawdown **-0.16513**, ready_ratio **0.25**.
- Fixed blend mean ICIR **0.04767**, worst drawdown **-0.31399**, ready_ratio **0.00**.
- Decision: **`no_stable_candidate`**, trade_ready **false**.

### Conclusion

Train-start misalignment was the primary readiness blocker across both markets.
Auto alignment restores pipelines without fabricated data, but underlying model
quality on the CN side is weak and expanded US universes still lack symbol
coverage. No further blend tuning or trade-ready claim is supported.

## Non-Trade-Ready Warning

> **Data-coverage alignment is a research tool, not a trading authorization.**
> An aligned start that passes all gates means the data exists — it does not
> mean the model is trade-ready. Trade readiness requires all decision gates
> (ICIR ≥ 0.30, drawdown ≥ −0.15, ready_ratio ≥ 0.75) to pass in
> `summarize_universe_robustness`.

## CLI Usage

```bash
# Strict mode (default) — uses requested train_start unchanged
python scripts/check_multi_market_data_readiness.py --train-start 2021-01-01

# Auto mode — discovers earliest viable start
python scripts/check_multi_market_data_readiness.py --train-start 2021-01-01 --alignment-mode auto

# CN validation with auto alignment
python scripts/run_cn_10d_validation.py --alignment-mode auto

# Universe robustness with auto alignment
python scripts/run_best_blend_universe_robustness.py --alignment-mode auto
```
