# QuantSkills volume/stat alpha review — Issue #966 Phase 0–1

Status: **Phase 0 complete. Phase 1 complete. Gate 0 PASS. Gate 1 PASS. Phase 2 may begin.**

This is the durable handoff record. The machine-readable checkpoints are:

- `data/research/quantskills_volume_stat_alpha/phase0_phase1_manifest.json`
- `data/research/quantskills_volume_stat_alpha/gate1_feature_quality.json`

## Fixed identities

- Alpha Engine research base: `52b8ec3ade1bc02f61dd6ed037c7055b32237453`.
- External source: `quantskills/skill-quant-factor-volume-stat-alpha` at `b169f31106f748b8746c4c1028c162e95f7277f4`.
- External license: GPL-3.0-only. The external repository remains an idea/provenance source only; no external implementation is vendored.
- US baseline remains `us_x1_2`; CN baseline remains `cn_x1_2`.
- Phase 0–1 changes no baseline model, label, portfolio rule, cost rule, universe membership, or trade-readiness status.

## Phase 0 result

The external 216-factor corpus reduces to nine mechanisms with 24 parameter/transform variants each. We therefore keep the pinned external `factor_index.json` as row-level provenance and make decisions at mechanism level rather than copying 216 local definitions.

| Mechanism | Decision |
| --- | --- |
| `volume_ratio` | already covered by canonical `ohlcv.liquidity.volume_vs_ma_*` |
| `volume_z` | defer |
| `dollar_volume` | defer |
| `price_volume_corr` | reuse package-backed Alpha158; US probe `qlib_alpha158.cord10`, CN x1.2 already uses `qlib_alpha158.cord5` |
| `obv_slope` | genuinely new first-wave information family; implement one independent signed-volume-flow proxy |
| `ts_rank_close` | reuse package-backed `qlib_alpha158.rank20` |
| `ts_rank_volume` | defer until price-rank ablation justifies widening |
| `ret_skew` | later risk/regime research |
| `ret_kurt` | later risk/regime research |

**Gate 0: PASS.** The 216 external `pass` statuses are not Alpha Engine promotion evidence: their validation is 5-day on CN98/US50, whereas the governed Alpha Engine problem is 10-session US87/CN130. External results are priors only.

## Phase 1 implementation

Only one new factor definition was necessary. It now lives in the normal schema-v2 canonical research library:

`configs/factor_libraries/volume_stat_research.yaml`

Factor:

- ID: `volume_stat_research.signed_volume_balance_10d`
- expression: `Sum(Sign($close-Ref($close,1))*$volume,10)/(Mean($volume,10)+1e-12)`
- required fields: close, volume
- markets: US, CN
- minimum lookback: 10 sessions
- status after Gate 1: `candidate`

The earlier temporary Python factor-set path was deleted. There is now one definition and one evaluator path. The factor uses existing Qlib `Sign`, `Sum`, `Mean`, and `Ref` operators; no cumulative-OBV runtime, factor DSL, compatibility layer, or second evaluator was added.

The other first-wave mechanisms continue to reuse existing Alpha158 definitions:

- price-volume correlation: `qlib_alpha158.cord10` for US research; CN already has `qlib_alpha158.cord5` in x1.2;
- price time-series rank: `qlib_alpha158.rank20`.

## Gate 1 implementation

Gate 1 is a structural feature-quality gate only. It deliberately loads no forward-return label, computes no IC, and trains no model. That keeps Phase 1 separate from Phase 2 selection evidence.

Canonical contracts:

- `configs/research_paradigms/us_issue966_phase1_feature_quality_v1.yaml`
- `configs/research_paradigms/cn_issue966_phase1_feature_quality_v1.yaml`

Evaluator and CLI:

- `src/research/factor_feature_quality.py`
- `scripts/run_factor_feature_quality.py`

CI/reproduction path:

- `.github/workflows/issue966-phase1-factor-quality.yml`

The workflow stages exactly the governed universe plus benchmark, builds the existing Qlib provider at cutoff `2026-06-30`, then checks finite coverage, inf/constant behavior, Qlib expression future-window dependency, deterministic reproduction, and symbol isolation.

## Gate 1 evidence

Final authoritative run: **GitHub Actions run `31941435349`**, head `7e74cb7870230cd07eff26f65f7170455f61d31d`.

### US87

- universe: `us_selected_equities_v2`, 87 requested symbols;
- provider identity: `c78ade39f63823d2f7089947831387803caae51b53073ae25fed2000f2a6f36c`;
- provider cutoff: `2026-06-30`; latest available calendar day in committed US sources: `2026-06-24`;
- finite factor rows: 108,346;
- minimum post-warm-up coverage: 100%; maximum end gap: 6 days;
- inf count: 0; near-constant: false;
- Qlib expression window: 10 past sessions, 0 future sessions;
- deterministic digest reproduced exactly: `9b31cc5f0c77051b5a2686cfdd4b255fa2e5bbdbe578f1968449724acd4e1dc6`;
- isolation probes `AAOI`, `AEHR`, `KLAC`: all exact matches;
- artifact: `9262151971`, digest `sha256:a48f7f40cfe85e264f466108c4b89ee514dffd9fa718bd9ac93223c3c1499076`.

### CN130

- universe: `cn_selected_equities_v3`, 130 requested symbols;
- provider identity: `6f17a9eba541159a4cb472721b32758f6bac4892d1a917730fa1b62e9d455980`;
- provider cutoff/calendar end: `2026-06-30`;
- finite factor rows: 163,608;
- minimum post-warm-up coverage: 99.7807%; maximum end gap: 0 days;
- inf count: 0; near-constant: false;
- Qlib expression window: 10 past sessions, 0 future sessions;
- deterministic digest reproduced exactly: `8a64610cce478cd74c86fe2e55510f548a87a58f52c8d44c3cbcf1affa155296`;
- isolation probes `000001`, `600009`, `688676`: all exact matches;
- artifact: `9262153816`, digest `sha256:70bb4c29b584a83f41949703941bb59f73da16c1a5aefedee9c063522d000043`.

**Gate 1: PASS.** The signed-volume factor is promoted from `unvalidated_formula` to research `candidate`. This is not an alpha result and does not imply trade readiness.

## Phase 2 boundary

Phase 2 may now test information value, with the current model family, 10-session label, universe, portfolio construction, costs, and data boundaries frozen.

The first-wave ablation set is:

1. `volume_stat_research.signed_volume_balance_10d` — genuinely new signed-volume-flow mechanism;
2. `qlib_alpha158.cord10` — US price-volume-correlation probe; do not present price-volume correlation as a new CN mechanism because CN x1.2 already contains `cord5`;
3. `qlib_alpha158.rank20` — price time-series-rank probe.

Do not widen to transform sweeps, `ts_rank_volume`, skew, or kurtosis before these three mechanism-level probes establish incremental value. Do not mutate `us_x1_2` or `cn_x1_2` during the ablation itself.

## Handoff rules

A new agent should start from Issue #966 plus the two JSON checkpoints above. It should not redo the external 216-factor inventory, create a QuantSkills runtime, duplicate CORD/RANK formulas, or add a fallback factor engine. The next legitimate work item is Phase 2 ablation under the frozen governed contracts.
