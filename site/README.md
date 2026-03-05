# Trading Assistant Static Dashboard

This is the static frontend for the AI Trading Assistant, designed to be hosted on GitHub Pages.

## How it works
1.  **Local Execution**: Run your training/backtest pipelines locally.
2.  **Export**: Run `python scripts/export_static_site_data.py` to generate the JSON data and copy reports into `site/`.
3.  **Push**: Commit and push the changes in the `site/` folder to GitHub.
4.  **Deploy**: GitHub Actions automatically deploys the content to your Pages site.

## Local Preview
To preview the site locally without a backend:
```bash
python -m http.server 8081 --directory site
```
Then open `http://localhost:8081` in your browser.

## Directory Structure
- `index.html`: Main entry point.
- `app.js`: Frontend logic (data fetching and UI population).
- `styles.css`: Custom styles.
- `data/`: JSON datasets exported from local SQLite.
- `reports/`: HTML report files copied from the main `reports/` directory.
