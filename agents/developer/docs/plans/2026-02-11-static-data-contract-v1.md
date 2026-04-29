# Static Data Contract v1.0 (2026-02-11)

This contract defines the structure of JSON files consumed by the static site.

---

## 1. `manifest.json`
Central index for the static site.
```json
{
  "generated_at": "YYYY-MM-DD HH:MM:SS",
  "snapshot_id": "watchlist-day-YYYY-MM-DD",
  "markets": ["us", "cn"],
  "stats": {
    "total_models": 10,
    "total_reports": 50
  }
}
```

---

## 2. `models.json`
List of registered model versions.
```json
[
  {
    "id": "model_id",
    "tag": "LGBM_v1",
    "market": "us",
    "metrics": {
      "annualized_return": 0.15,
      "max_drawdown": -0.05
    },
    "feature_importance": { "feat1": 0.8, "feat2": 0.2 }
  }
]
```

---

## 3. `curves/{run_id}.json`
Equity curve data for a specific run.
```json
{
  "run_id": "run_id",
  "points": [
    { "date": "2025-01-01", "nav": 1.0, "drawdown": 0.0 },
    { "date": "2025-01-02", "nav": 1.01, "drawdown": 0.0 }
  ]
}
```

---

## 4. `arena.json`
Latest arena leaderboard.
```json
{
  "arena_name": "Global Arena",
  "date": "2025-02-11",
  "leaderboard": [
    { "rank": 1, "name": "Model A", "nav": 1.25, "daily_return": 0.01 }
  ]
}
```

---

## 5. `reports.json`
Index of available HTML reports.
```json
[
  {
    "id": "report_id",
    "type": "backtest",
    "ref_id": "run_id",
    "date": "2025-02-11",
    "html_path": "reports/backtest_run_id.html"
  }
]
```
