# AlphaEngine V2

## 证据驱动的量化策略研究引擎

AlphaEngine 用固定研究契约、时间有效的数据、walk-forward 验证和 fail-closed 决策，判断候选信号是否具有可信的基准相对收益。

> **Current status — 2026-08-02**
>
> - AlphaEngine 是研究专用系统，没有模型达到 `trade_ready`。
> - GitHub Pages/PWA **Research Artifact Studio** 是唯一支持的 Web 产品方向。
> - Python 数据、训练、回测与研究工作通过 CLI、脚本和工作流执行。
> - 前端只读取版本化研究成果包，不负责训练、数据刷新、模型变更或交易执行。
> - 原 FastAPI、本地登录 Web、PM2 和 API 容器架构已进入冻结退役期，见 [#316](https://github.com/liuh886/alpha_engine/issues/316)。

核心研究结论：

- [`docs/research/static_to_pit_alpha_diagnosis_2026-07-29.md`](docs/research/static_to_pit_alpha_diagnosis_2026-07-29.md)
- [`docs/research/lgbm_xgb_ranker_pit_robustness_2026-07-29.md`](docs/research/lgbm_xgb_ranker_pit_robustness_2026-07-29.md)
- [`docs/10d_universe_robustness_report.md`](docs/10d_universe_robustness_report.md)
- [`docs/methodology.md`](docs/methodology.md)

## 1. Web product: Research Artifact Studio

The Research Artifact Studio is a static, installable PWA deployed through GitHub Pages:

- no backend or login required;
- opens the published example/research bundle;
- opens a local Alpha Engine bundle from a directory, file set or ZIP;
- verifies manifest paths, byte sizes and SHA-256 digests;
- keeps selected local files in the browser and does not upload them;
- supports an offline application shell after the first successful visit.

Open the deployed application at:

- <https://liuh886.github.io/alpha_engine/>

In **Library**, choose the published bundle or open a local folder/ZIP containing `alpha-engine-bundle.json`.

## 2. Produce a research bundle

Alpha Engine uses Astral `uv`; `uv.lock` is the dependency source of truth.

```bash
git clone https://github.com/liuh886/alpha_engine.git
cd alpha_engine
uv sync --extra dev
```

Run the required research pipeline, for example:

```bash
make data
make train-us
make backtest
```

Export the canonical frontend artifact:

```bash
make research-bundle
```

This produces:

```text
artifacts/research-bundle/
  alpha-engine-bundle.json
  data/
  reports/
  notebooks/
  docs/
```

Open that folder from the PWA Library. The frontend reads only files declared by the manifest.

## 3. Target architecture

```text
Python data/model/backtest pipelines
        ↓
versioned research bundle + reports/notebooks
        ↓
GitHub Pages / PWA / local bundle reader
```

Architecture rules:

- the Python research pipeline is authoritative;
- `alpha-engine-bundle.json` is the frontend data boundary;
- execution belongs to Python CLI/scripts/workflows;
- the browser is read-only;
- missing or incompatible evidence fails visibly;
- no output authorizes live or automated trading.

The legacy-Web retirement policy and inventory are maintained in:

- [`docs/architecture/legacy_web_retirement.md`](docs/architecture/legacy_web_retirement.md)
- [`docs/architecture/legacy_web_inventory.json`](docs/architecture/legacy_web_inventory.json)

## 4. Research contract

Both CN and US canonical research use a fixed 10-trading-day paradigm:

| Property | Contract |
| --- | --- |
| Forecast horizon | 10 trading sessions |
| Holding period | 10 trading sessions |
| Rebalance cadence | 10 trading sessions |
| Economic return | `Ref($close, -10) / $close - 1` |
| Training/evaluation boundary | processed rank labels for fitting; raw returns for economics |
| Validation | expanding half-year OOS windows with a 10-session embargo |
| Benchmark | CSI 300 for CN; QQQ for US |
| Scope | `research_only=true` |

Research execution is bound to versioned specs in `configs/research_paradigms/`. Missing benchmark dates, universe hashes, provider lineage, coverage evidence or minimum windows fail closed.

## 5. Universe validity

Static curated universes remain useful for exploratory diagnostics, but they are not unbiased historical opportunity sets.

The current US robustness path uses:

- official Nasdaq-100 membership at each OOS half-year start;
- the latest semiannual membership known on each training date;
- manifest-bound provider identity and membership hashes;
- explicit missing-symbol reporting rather than zero filling or current-member substitution.

This is window-start/semiannual point-in-time research, not full daily PIT. China research still uses static curated membership and therefore remains survivorship-biased.

## 6. Latest model-effectiveness finding

The fixed LightGBM/XGBoost comparison uses the same features, processed daily rank target, 100-round budget, 10-session embargo, raw OOS returns, Top-15 portfolio, 20 bps cost and QQQ benchmark.

| Candidate | Static curated relative excess | PIT NDX relative excess | PIT positive windows | PIT worst drawdown |
| --- | ---: | ---: | ---: | ---: |
| LightGBM LambdaRank | +65.04% | -20.49% | 1/4 | -26.11% |
| XGBoost `rank:ndcg` | +70.35% | -34.08% | 1/4 | -25.59% |

The algorithm-family difference is small compared with the universe-validity problem. The next approved experiment is frozen static-to-PIT attribution, not another hyperparameter or factor-window search.

## 7. Common commands

```text
make doctor           validate the Python research environment
make data             update market data
make train-us         run the configured US training path
make train-cn         run the configured CN training path
make backtest         run the configured backtest path
make research-bundle  export the canonical versioned bundle
make breakfast        generate the daily research brief
make ci               run repository quality gates locally
```

## 8. Frontend contributor workflow

The frontend may be run as a static development server for UI work. It must not require or silently connect to FastAPI.

```bash
cd qlib-dashboard
npm ci
VITE_RUNTIME_MODE=static_artifact npm run dev
```

Production validation:

```bash
cd qlib-dashboard
npx tsc --noEmit
npm run lint
npm test
VITE_RUNTIME_MODE=static_artifact npm run build
npx playwright test --config=playwright.static.config.ts
```

## 9. Deprecated local-Web compatibility

The following path is retained temporarily only for migration and removal work:

```bash
make legacy-web-dev
```

It starts the old Vite + FastAPI stack. Do not use it as the product quick start and do not add new endpoints, API calls, authentication behavior or operational UI.

The compatibility alias `make dev`, PM2 launchers, API Docker/Compose stack, Basic Auth/CORS settings, API tests and `connected_research` mode will be removed in sequenced PRs under #316.

## 10. Scope and safety

- No browser-side model training.
- No broker integration or order execution.
- No hosted upload or cloud synchronization of local bundles.
- No silent fallback from missing artifact evidence to backend data.
- No feature-importance view is presented as proof of factor effectiveness.
- `research_only=true`, `trade_ready=false`.

More detail is available in `docs/methodology.md`, `docs/product/frontend_artifact_studio.md`, `AGENTS.md` and `scripts/README.md`.
