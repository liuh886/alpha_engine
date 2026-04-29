# Static Site MVP Scope (2026-02-11)

## 1. Overview
The goal of the static site is to provide a read-only, high-performance dashboard hosted on GitHub Pages. It will display the latest results from the Trading Assistant's local execution without requiring a live backend.

## 2. MVP Modules (Included)
1.  **Overview**: High-level system status, last update time, and market summaries.
2.  **Model Leaderboard**: Rankings of all registered model versions across markets.
3.  **Backtest Analysis**: Interactive charts for equity curves and drawdowns of specific runs.
4.  **Arena Daily**: Daily settlement results and rankings from the Global Arena.
5.  **Report Index**: A list of generated HTML reports (Backtest/Arena) with links.

## 3. Out of Scope (Not Included)
- **Live Data Update**: Cannot trigger `scripts/update_data.py`.
- **Training/Backtest Execution**: Cannot trigger new runs or training jobs.
- **Task Management**: No `/api/jobs` visibility or control.
- **Live Logs**: No real-time SSE log streaming.
- **Database Write Actions**: No model promotion or participant deletion.

## 4. Technical Approach
- **Data Source**: The site will read from `site/data/*.json`.
- **Hosting**: GitHub Pages (Static).
- **Frontend**: Vanilla JS or lightweight React/Tailwind (Directly servable).
- **Automation**: A GitHub Action will deploy the `site/` folder after local execution pushes new data.

## 5. Success Criteria
- The site loads in under 2 seconds.
- All 5 MVP modules are fully functional with static data.
- Zero dependencies on a running Python server at runtime.
