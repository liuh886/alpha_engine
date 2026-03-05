# Trend Strategy Sell Rules (Biweekly) — Design

## Goal
Reduce turnover for the trend strategy by enforcing a biweekly rebalance cadence and stricter sell rules, while preserving trend protection and model ranking signals.

## Constraints
- Rebalance frequency: biweekly (~10 trading days).
- Minimum holding period: 10 **calendar** days.
- Sell triggers:
  - Break of MA60 (trend stop).
  - Model score falls out of Top20.
- Portfolio: Top5, long-only, equal-weight.
- Ranking-based sells are evaluated only on rebalance days.

## Proposed Rules
1) **Minimum holding period (calendar days)**
   - Any newly opened position is locked for 10 calendar days.
   - Within lock period, ignore MA60 and rank-based sell signals.

2) **Trend break sell (MA60)**
   - After the holding period, if price < MA60, sell immediately at next evaluation point.

3) **Rank-based sell (Top20)**
   - After holding period, if instrument falls outside Top20, sell on rebalance day.

4) **Rebalance day actions**
   - Process sell candidates (trend break + rank out) that are beyond holding period.
   - Refill to Top5 using latest ranks; if fewer candidates available, hold cash.

## Edge Handling
- Missing price/MA data: defer decision, keep holding and re-check on next evaluation.
- Overlap of sell signals: trend break has higher priority than rank out.
- Lock period conflicts: holding period overrides all sell signals.

## Data Flow
- **Configs**: add `rebalance_frequency=biweekly`, `min_hold_days=10`, `sell_on_ma=60`, `sell_rank_threshold=20` to strategy profile/workflow config.
- **Backtest logic**: enforce lock period, compute MA60, and apply sell rules.
- **Dashboard**: display these parameters in model params to explain turnover behavior.

## Testing/Validation
- Compare turnover, max drawdown, and excess return vs. baseline.
- Verify average holding period increases and turnover decreases.
- Confirm model params shown in dashboard match config values.
