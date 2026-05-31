# Model Training Methodology

This document describes the complete methodology for how AlphaEngine trains models, evaluates strategies, and controls risk. It is the authoritative reference for understanding and validating model outputs.

---

## 1. Data Preparation

### Stock Pool

| Market | Source | Instruments | Benchmark |
|--------|--------|-------------|-----------|
| US | `data/watchlist/instruments/us.txt` | 118 stocks (S&P 500 subset + growth picks) | QQQ |
| CN | `data/watchlist/instruments/cn.txt` | 206 stocks (CSI 300 subset + watchlist) | 000300 (CSI 300) |

Instruments are listed in `configs/watchlist.yaml`. Each line specifies symbol, start date, and end date.

### Data Source

- **Provider**: Qlib binary format stored in `data/watchlist/features/{SYMBOL}/`
- **Frequency**: Daily (`day.txt` calendar, 1619 trading days from 2020-01-02 to 2026-04-03)
- **Features per stock**: close, open, high, low, volume, amount, vwap, money, factor
- **Format**: Little-endian float32 binary (`.bin`), NaN for missing data

### Data Quality

Before training, a data quality check runs via `src/assistant/data_quality_check.py`:
- Stale instruments (no data in last 5 trading days)
- Parse errors in CSV sources
- Missing feature files

Results are stored in `DataQualityIndex` (SQLite) and surfaced in the dashboard.

---

## 2. Feature Engineering

The model uses **Alpha158** — a standard Qlib feature set of 158 technical factors derived from OHLCV data. An additional 5 custom features bring the total to **163 features**.

### Feature Categories

| Category | Count | Examples | Lookback Windows |
|----------|-------|----------|-----------------|
| **K-bar** | 9 | `(close-open)/open`, `(high-low)/open`, `(2*close-high-low)/open` | Current bar |
| **Price Reference** | 5 | `open/close`, `high/close`, `low/close`, `vwap/close` | Current bar |
| **Rolling Mean** | 5 | `Mean(close, 5)/close`, `Mean(close, 20)/close` | 5, 10, 20, 30, 60 |
| **Rolling Std** | 5 | `Std(close, 5)/close`, `Std(close, 20)/close` | 5, 10, 20, 30, 60 |
| **Slope** | 5 | `Slope(close, 5)/close` | 5, 10, 20, 30, 60 |
| **R-square** | 5 | `Rsquare(close, 5)` | 5, 10, 20, 30, 60 |
| **Residual** | 5 | `Resi(close, 5)/close` | 5, 10, 20, 30, 60 |
| **Max/Min** | 10 | `Max(high, 5)/close`, `Min(low, 5)/close` | 5, 10, 20, 30, 60 |
| **Quantile** | 10 | `Quantile(close, 5, 0.8)/close` | 5, 10, 20, 30, 60 (80th & 20th) |
| **Rank** | 5 | `Rank(close, 5)` | 5, 10, 20, 30, 60 |
| **Williams %R** | 5 | `(close-Min(low,5))/(Max(high,5)-Min(low,5))` | 5, 10, 20, 30, 60 |
| **Index Max/Min** | 15 | `IdxMax(high, 5)/5`, `IdxMin(low, 5)/5`, `(IdxMax-IdxMin)/N` | 5, 10, 20, 30, 60 |
| **Price-Volume Corr** | 10 | `Corr(close, Log(volume+1), 5)` | 5, 10, 20, 30, 60 |
| **Up/Down Days** | 10 | `Mean(close>Ref(close,1), 5)` | 5, 10, 20, 30, 60 |
| **Up-Down Balance** | 5 | `Mean(up,5) - Mean(down,5)` | 5, 10, 20, 30, 60 |
| **RSI-like** | 15 | `Sum(gain,5)/(Sum(|change|,5)+eps)` (up, down, balance variants) | 5, 10, 20, 30, 60 |
| **Volume Stats** | 10 | `Mean(volume,5)/volume`, `Std(volume,5)/volume` | 5, 10, 20, 30, 60 |
| **Volume Volatility** | 5 | `Std(ret*volume, 5)/Mean(ret*volume, 5)` | 5, 10, 20, 30, 60 |
| **Volume Momentum** | 10 | Up/down volume balance | 5, 10, 20, 30, 60 |
| **Returns** | 3 | `close/Ref(close,5)-1`, `close/Ref(close,10)-1`, `close/Ref(close,20)-1` | 5, 10, 20 |
| **Other** | 2 | `Std(close,10)`, `volume/Ref(volume,10)-1` | 10 |
| **Custom MA Dev** | 4 | `mkt_{us/cn}_ma20_dev`, `mkt_{us/cn}_ma60_dev` | Market-level |

### Source

Features are defined in `configs/us_lgbm_workflow.yaml` (lines 46-243) and `configs/cn_lgbm_workflow.yaml`.

---

## 3. Label Definition

The prediction target is the **10-day forward return**:

```
label = Ref($close, -10) / Ref($close, -1) - 1
```

This means: the model predicts the cumulative return from tomorrow to 10 days from now. The signal is used to rank stocks — higher predicted return = stronger buy signal.

---

## 4. Preprocessing

Two processors are applied before training:

1. **DropnaLabel** — Removes rows where the label is NaN (stocks near the end of the data window that don't have 10 days of future data).

2. **CSZScoreNorm (label)** — Cross-sectional z-score normalization of labels. For each date, the label values across all stocks are standardized to mean=0, std=1. This ensures the model learns relative ranking, not absolute return levels.

3. **CSZScoreNorm (feature)** — Cross-sectional z-score normalization of features during inference. For each date, each feature is standardized across all stocks.

---

## 5. Model: LightGBM

### Hyperparameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `loss` | mse | Mean squared error objective |
| `learning_rate` | 0.05 | Step size shrinkage |
| `max_depth` | 10 | Maximum tree depth |
| `num_leaves` | 128 | Maximum number of leaves per tree |
| `subsample` | 0.8789 | Row subsampling ratio (bagging) |
| `colsample_bytree` | 0.8879 | Feature subsampling ratio per tree |
| `lambda_l1` | 1.0 | L1 regularization |
| `lambda_l2` | 1.0 | L2 regularization |
| `num_threads` | 20 | Parallelism |
| `early_stopping_rounds` | 50 | Stop if validation loss doesn't improve for 50 rounds |

### Source

Defined in `configs/us_lgbm_workflow.yaml` (lines 8-20) and `configs/cn_lgbm_workflow.yaml`.

---

## 6. Train / Validation / Test Split

| Segment | Period | Purpose |
|---------|--------|---------|
| **Train** | 2021-01-01 to 2024-12-31 | Model learns patterns from 4 years of data |
| **Validation** | 2025-01-01 to 2025-12-31 | Early stopping uses this to prevent overfitting |
| **Test** | 2026-01-01 to 2026-04-03 | True holdout — model never sees this during training |

Validation and test are now separated. The test period (2026 Q1) is a true out-of-sample holdout that the model never sees during training or early stopping.

---

## 7. Evaluation Metrics

### Primary Metrics

| Metric | Formula | Good | Excellent | Poor |
|--------|---------|------|-----------|------|
| **Annualized Return** | `mean(daily_returns) × 252` | > 15% | > 25% | < 5% |
| **Information Ratio** | `annualized_return / tracking_error` | > 0.5 | > 1.0 | < 0.3 |
| **Max Drawdown** | `max((peak - trough) / peak)` | < 15% | < 10% | > 25% |

### Derived Metrics

| Metric | Calculation |
|--------|------------|
| **Total Return** | `(final_value / initial_value) - 1` |
| **Annual Volatility** | `std(daily_returns) × √252` |
| **Sharpe Ratio** | `annualized_return / annual_volatility` |
| **Alpha (excess return)** | `strategy_return - benchmark_return` |

### Benchmark Comparison

Every backtest is compared against:
- **US**: QQQ (Invesco QQQ Trust)
- **CN**: 000300 (CSI 300 Index)

The key question is: **does the strategy beat the benchmark after costs?**

---

## 8. Overfitting Controls

| Control | Implementation | Effect |
|---------|---------------|--------|
| **Early Stopping** | `early_stopping_rounds: 50` | Stops training when validation loss plateaus |
| **L1 Regularization** | `lambda_l1: 1.0` | Prunes unimportant features |
| **L2 Regularization** | `lambda_l2: 1.0` | Prevents large leaf weights |
| **Row Subsampling** | `subsample: 0.8789` | Each tree sees ~88% of data |
| **Feature Subsampling** | `colsample_bytree: 0.8879` | Each tree sees ~89% of features |
| **Cross-Sectional Norm** | `CSZScoreNorm` | Model learns rankings, not levels |
| **Immutable Metrics** | `src/common/metrics_extractor.py` | Exact metric values are frozen at compute time |

### Known Weaknesses

- **Single market per model**: No cross-market generalization.
- **Point-in-time bias**: Features use `Ref()` which respects time ordering, but the instrument list may include survivorship bias.

---

## 9. Strategy Execution: BiweeklyTrendStrategy

### Parameters

| Parameter | Value | Effect |
|-----------|-------|--------|
| `topk` | 5 | Hold top 5 ranked stocks |
| `rebalance_steps` | 10 | Rebalance every 10 trading days (~2 weeks) |
| `min_hold_days` | 10 | Minimum holding period before selling |
| `sell_ma_window` | 60 | 60-day moving average for sell signal |
| `sell_rank_threshold` | 20 | Sell if stock drops below rank 20 on rebalance day |
| `buy_score_threshold` | None | Only buy stocks with score above this threshold (e.g., 0) |
| `sell_score_threshold` | None | Sell stocks with score below this threshold (e.g., 0) |

### Execution Logic

1. **Every trading day**: Check existing positions for sell signals:
   - Stock price < 60-day MA → sell (after min_hold_days)
   - On rebalance days: stock rank >= 20 → sell (after min_hold_days)
   - On rebalance days: stock score < `sell_score_threshold` → sell (after min_hold_days)

2. **Every 10 trading days** (rebalance day):
   - Sell positions that meet sell criteria
   - Buy top-K stocks not currently held
   - If `buy_score_threshold` is set, only buy stocks with score above threshold
   - Position sizing: equal weight (`cash / available_slots`), capped at 15% per stock

3. **Transaction costs**: 10 bps (0.1%) each way, applied by Qlib exchange simulator

### Source

`src/strategies/biweekly_trend_strategy.py`

---

## 10. Risk Controls

### Position-Level Guards

| Guard | Rule | Source |
|-------|------|--------|
| **Max position size** | 15% of available cash per buy | `biweekly_trend_strategy.py:189` |
| **Limit threshold** | 9.5% daily move blocks trade | `us_lgbm_workflow.yaml:273` |
| **Tradability check** | Only trade liquid, non-suspended stocks | Strategy `is_stock_tradable()` |

### Portfolio-Level Guards

| Guard | Rule | Source |
|-------|------|--------|
| **MA20 Deviation** | Block trades if stock >20% above MA20 | `risk_monitor.py` extension |
| **Volatility Regime** | Check market volatility before entry | `risk_monitor.py` extension |
| **MDD Circuit Breaker** | 15% max drawdown triggers SYSTEM_PANIC | `risk_monitor.py:8` |

### System-Level Guards

| Guard | Rule | Source |
|-------|------|--------|
| **SYSTEM_PANIC** | Immediate halt of all agent tasks and backend jobs | `/api/system/panic` endpoint |
| **Emergency Kill** | Manual kill switch in sidebar | `Sidebar.tsx` panic button |

---

## 11. Model Promotion Gates

Before a model can be promoted to `RECOMMENDED` stage, it must pass all gates:

| Gate | Threshold | Purpose |
|------|-----------|---------|
| **Excess Return** | > 0% | Strategy must beat benchmark after costs |
| **Information Ratio** | >= 0.5 | Risk-adjusted return must be meaningful |
| **MDD Ratio** | <= 1.5x benchmark | Drawdown must not be excessive vs benchmark |
| **Net Return** | > 0% | Return after transaction costs must be positive |
| **Walk-Forward** | Required | Model must have walk-forward validation metadata |

Gate checks are enforced in `src/assistant/services/model_service.py:_check_promotion_gates()`.

---

## 12. Natural Language Strategy Compiler

The system supports generating strategy profiles from natural language descriptions via `src/assistant/services/strategy_compiler_service.py`.

### Supported Parameters

| Parameter | English Keywords | Chinese Keywords |
|-----------|-----------------|-----------------|
| Market | us, cn, nasdaq, s&p | 美股, 中国, a股 |
| Rebalance | weekly, biweekly, monthly | 一周, 双周, 月度 |
| TopK | top N, hold N, pick N | 持有N只, 选N |
| Sell MA | sell below ma(N), N-day ma | 跌破N日均线 |
| Buy Rule | positive score, score > X | 正分, 得分大于X |
| Sell Rule | negative score, score < X | 负分, 得分小于X |
| Capital | capital $N, start with N | 资金N, 本金N万 |

### Pipeline

1. NL text → `parse_natural_language()` → `strategy_profile.json`
2. `strategy_profile.json` → `compile_strategy_profile()` → Qlib YAML workflow
3. YAML → Qlib backtest engine

API: `POST /api/strategy/compile` with `{"text": "...", "market": "us"}`

---

## 13. Known Limitations

1. **Survivorship Bias**: Watchlist may exclude delisted stocks, inflating historical returns.
2. **No Slippage Model**: Exchange costs are fixed at 10bps; real slippage varies with volume.
3. **Single Model**: Only LightGBM is used. Ensemble methods (XGBoost, neural nets) are not explored.
4. **Fixed Hyperparameters**: No Bayesian optimization or grid search for hyperparameter tuning.
5. **Walk-Forward Not Yet Automated**: Promotion gates require walk-forward validation, but the automated rolling-window pipeline is not yet implemented.
