---
name: "Biweekly Trend Strategy V2"
strategy_class: "BiweeklyTrendStrategy"
topk: 5
rebalance_steps: 10
min_hold_days: 10
sell_ma_window: 60
sell_rank_threshold: 20
benchmark: "QQQ"
initial_cash: 10000
provider_uri: "data/watchlist"
model_path: "models/us_classifier.pkl"
---

# Biweekly Trend Strategy (V2 MVP)

This is the migrated version of the Biweekly Trend strategy, adapted for AlphaEngine V2's "Self-contained Strategy Unit" architecture.

### Key Logic:
1. **Model Driven**: Uses a classifier (Prob > 0.5) to rank assets.
2. **Trend Filter**: Exits positions if the price falls below the 60-day Moving Average.
3. **Bi-weekly Rebalance**: Rebalances the top 5 assets every 10 trading steps.
4. **Self-contained**: All rules and class definitions live within this folder.

### Configuration:
Parameters are defined in the YAML frontmatter above. Moving this folder to another AlphaEngine V2 instance will preserve all settings and logic.
