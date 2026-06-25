# Strategy Audit & Model Exploration Plan
> Generated: 2026-06-25

## 1. Current Strategy Assessment

### Strategy Mechanics
| Parameter | Value | Assessment |
|---|---|---|
| Signal | 10-day forward return prediction (LightGBM) | ✅ Standard alpha signal |
| Selection | Top-K equal-weight | ✅ Simple, robust |
| Holding Period | 10 days | ✅ Matches signal horizon |
| Rebalancing | Daily layering (1/10 capital per day) | ✅ Smooth equity curve |
| Cost Model | 20bps round-trip | ✅ Conservative, realistic |
| Benchmark | QQQ (US) / CSI300 (CN) | ✅ Appropriate |

### Performance Summary (layered backtest, 2025-01 to 2026-06)
| Model | Market | Top-K Sharpe | Rank Spread | IC | Verdict |
|---|---|---|---|---|---|
| cn_model_cn_best_v1 | CN | 0.12 (K=15) | 2-7% | 0.022 | ⚠️ Weak but directional |
| us_model_us_absret | US | 0.16 (K=15) | ~0% | 0.037 | ❌ No ranking power |
| us_model_us_excess | US | 0.17 (K=15) | ~0% | 0.001 | ❌ No ranking power |
| OLD us_model (mlruns) | US | 2.04 (K=15) | N/A | N/A | ✅ Strong but OUTDATED |

### K-Sensitivity (cn_model_cn_best_v1)
```
K=5:  sharpe=0.137  TOP-BOT spread=6.9%   ← BEST
K=10: sharpe=0.135  TOP-BOT spread=5.2%
K=15: sharpe=0.123  TOP-BOT spread=2.4%
K=20: sharpe=0.121  TOP-BOT spread=2.4%   ← WORST
```
**Finding**: Smaller K = better performance. Model identifies a few good stocks but ranking quality degrades with more holdings.

### Verdict
- **Strategy is REASONABLE** for CN market (has ranking power, positive spread)
- **Strategy FAILS for US market** (top ≈ bottom, no ranking power)
- Old mlruns models (140 days stale) had strong performance → training quality matters

---

## 2. Data Foundation

| Metric | Status | Action |
|---|---|---|
| Calendar | 2026-06-25 ✅ | Latest |
| US Data | Unknown | Run update_data.py --market us |
| CN Data | 68/211 failed (32%) | Run update_data.py --market cn |
| Quality Snapshot | None (failed) | Publish after data fix |
| Symbols | 348 configured | Adequate for both markets |

---

## 3. Model Inventory

### Production Models (in dashboard)

| ID | Age | Market | Type | Status |
|---|---|---|---|---|
| us_model_20260205_144902 | 140d | US | LightGBM (mlruns) | ❌ Stale — retrain |
| us_model_20260205_145314 | 140d | US | LightGBM (mlruns) | ❌ Stale — retrain |
| us_model_us_absret_20260621 | 4d | US | LightGBM (artifact) | ⚠️ No ranking power |
| us_model_us_excess_20260621 | 4d | US | LightGBM (artifact) | ❌ No ranking power |
| cn_model_cn_best_v1_20260621 | 4d | CN | LightGBM (artifact) | ⚠️ Weak but works |

### Stale/Pipeline Models (not in dashboard)

| ID | Run ID | Market | Notes |
|---|---|---|---|
| us_model_us_absret | a8a1b3b6 | US | Duplicate of current |
| us_model_us_excess | 69ae9ee6 | US | Duplicate of current |
| cn_model_cn_best_v2 | (empty) | CN | Placeholder — skip |
| cn_model_optimal_alpha158 | (empty) | CN | Placeholder — skip |

---

## 4. Model Exploration Plan

### Phase 1: Fix Foundation
- [ ] Repair data quality → publish valid snapshot
- [ ] Verify all symbols have valid OHLCV data
- [ ] Run consistency checks between providers

### Phase 2: Retrain Baselines
- [ ] Retrain US models with updated data (to 2026-06-25)
- [ ] Retrain CN models with latest data
- [ ] Compare new vs old performance

### Phase 3: Feature Engineering
- [ ] Add momentum features (5d, 20d, 60d)
- [ ] Add volume/volatility features
- [ ] Add sector/industry features
- [ ] Test feature importance → prune weak features

### Phase 4: Model Variants
- [ ] XGBoost vs LightGBM comparison
- [ ] Different label horizons (5d, 10d, 20d)
- [ ] Different label types (absolute, excess, rank, z-score)
- [ ] Ensemble: combine absret + excess models

### Phase 5: Strategy Optimization
- [ ] Top-K optimization (grid search K=3..30)
- [ ] Rebalance frequency sweep (5d, 10d, 15d, 20d)
- [ ] Market-cap weighting vs equal-weight
- [ ] Dynamic position sizing based on confidence

### Phase 6: Risk Management
- [ ] Stop-loss rules
- [ ] Maximum drawdown limits
- [ ] Sector concentration limits
- [ ] Market regime filter (bear/bull detection)

---

## 5. Key Decisions Needed

1. **US Model**: Current models have zero ranking power. Options:
   - A) Investigate why old mlruns model (140d ago) had sharpe=2.04 but new ones don't
   - B) Try different feature sets / label types
   - C) Accept that US large-cap is efficient and focus on CN

2. **CN Model**: Weak but directional. Options:
   - A) Optimize features and retrain for better IC
   - B) Accept current performance and improve execution

3. **Strategy Parameters**: Lock in K=5 as optimal (supported by data)
