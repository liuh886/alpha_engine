# AlphaEngine V2

## 证据驱动的量化策略研究引擎

AlphaEngine 用固定研究契约、时间有效的数据、walk-forward 验证和 fail-closed 决策，判断候选信号是否具有可信的基准相对收益。

> **Current status — 2026-08-02**
>
> - AlphaEngine 是研究专用系统，没有模型达到 `trade_ready`。
> - GitHub Pages/PWA **Research Artifact Studio** 是唯一支持的 Web 产品。
> - Python 数据、训练、回测与研究工作通过 CLI、脚本和工作流执行。
> - 前端只读取版本化研究成果包，不负责训练、数据刷新、模型变更或交易执行。
> - 旧本地服务器、登录界面、进程管理和 API 容器架构已经完成退役。

核心研究结论：

- [`docs/research/static_to_pit_alpha_diagnosis_2026-07-29.md`](docs/research/static_to_pit_alpha_diagnosis_2026-07-29.md)
- [`docs/research/lgbm_xgb_ranker_pit_robustness_2026-07-29.md`](docs/research/lgbm_xgb_ranker_pit_robustness_2026-07-29.md)
- [`docs/10d_universe_robustness_report.md`](docs/10d_universe_robustness_report.md)
- [`docs/methodology.md`](docs/methodology.md)

## 1. Web product: Research Artifact Studio

Research Artifact Studio 是通过 GitHub Pages 发布的静态、可安装 PWA：

- 不需要后端或登录；
- 可读取公开发布的研究成果包；
- 可从本地目录、文件集合或 ZIP 打开 Alpha Engine 成果包；
- 校验 manifest 路径、文件大小和 SHA-256；
- 本地文件只保留在浏览器内，不上传；
- 首次成功访问后支持离线应用壳。

公开入口：

- <https://liuh886.github.io/alpha_engine/>

在 **Library** 中选择公开成果，或打开包含 `alpha-engine-bundle.json` 的本地文件夹或 ZIP。

## 2. 安装研究环境

Alpha Engine 使用 Astral `uv`，`uv.lock` 是 Python 依赖来源：

```bash
git clone https://github.com/liuh886/alpha_engine.git
cd alpha_engine
uv sync --extra dev
```

常用检查：

```bash
make doctor
make test
make ci
```

## 3. 生成研究成果包

先运行所需研究流程，例如：

```bash
make data
make train-us
make backtest
```

再导出前端唯一接受的成果边界：

```bash
make research-bundle
```

输出结构：

```text
artifacts/research-bundle/
  alpha-engine-bundle.json
  data/
  reports/
  notebooks/
  docs/
```

前端只读取 manifest 声明的文件。缺失、摘要不匹配或版本不兼容都会明确失败，不会从其它来源补齐。

## 4. 当前架构

```text
Python data/model/backtest pipelines
        ↓
versioned research bundle + reports/notebooks
        ↓
GitHub Pages / PWA / local bundle reader
```

架构规则：

- Python 研究流水线是事实来源；
- `alpha-engine-bundle.json` 是浏览器数据边界；
- 执行属于 Python CLI、脚本和工作流；
- 浏览器永久只读；
- 缺失或不兼容证据必须显式失败；
- 任何输出都不构成实盘或自动交易授权。

退役记录和完成态门禁：

- [`docs/architecture/legacy_web_retirement.md`](docs/architecture/legacy_web_retirement.md)
- [`docs/architecture/legacy_web_inventory.json`](docs/architecture/legacy_web_inventory.json)

## 5. 研究契约

CN 和 US 的标准研究都使用固定的 10 个交易日范式：

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

研究执行绑定到 `configs/research_paradigms/` 中的版本化规范。基准日期、股票池哈希、provider lineage、覆盖证据或最小窗口缺失时均 fail closed。

## 6. Universe validity

静态精选股票池适合探索性诊断，但不是无偏的历史机会集。

当前 US 稳健性路径使用：

- 每个 OOS 半年窗口起点的 Nasdaq-100 官方成员；
- 训练日期当时已知的最近一次半年度成员表；
- manifest 绑定的 provider identity 和 membership hashes；
- 显式报告缺失标的，而不是补零或替换为当前成分股。

这属于窗口起点/半年度 point-in-time 研究，不是每日完整 PIT。中国研究仍使用静态精选成员，因此仍存在幸存者偏差。

## 7. 当前模型有效性判断

固定 LightGBM/XGBoost 对比使用相同特征、processed daily rank target、100-round budget、10-session embargo、raw OOS returns、Top-15 portfolio、20 bps 成本和 QQQ 基准。

| Candidate | Static curated relative excess | PIT NDX relative excess | PIT positive windows | PIT worst drawdown |
| --- | ---: | ---: | ---: | ---: |
| LightGBM LambdaRank | +65.04% | -20.49% | 1/4 | -26.11% |
| XGBoost `rank:ndcg` | +70.35% | -34.08% | 1/4 | -25.59% |

算法家族差异小于股票池有效性问题。下一项获批实验是冻结的 static-to-PIT 归因，而不是继续进行超参数或因子窗口搜索。

## 8. 常用命令

```text
make doctor           检查 Python 研究环境
make data             更新市场数据
make train-us         运行 US 训练流程
make train-cn         运行 CN 训练流程
make backtest         运行标准回测流程
make research-bundle  导出版本化研究成果包
make static-pwa       构建零 API 的 Research Artifact Studio
make breakfast        生成每日研究简报
make ci               运行仓库质量门禁
```

## 9. 前端开发与验证

```bash
cd qlib-dashboard
npm ci
VITE_RUNTIME_MODE=static_artifact npm run dev
```

生产验收：

```bash
cd qlib-dashboard
npx tsc --noEmit
npm run lint
npm test
VITE_RUNTIME_MODE=static_artifact npm run build
npx playwright test --config=playwright.static.config.ts
```

生产前端只允许 `static_artifact` 和 `local_artifact` 两种来源模式；不得增加网络取数、后台任务或写操作。

## 10. Scope and safety

- No browser-side model training.
- No broker integration or order execution.
- No hosted upload or cloud synchronization of local bundles.
- No silent fallback from missing artifact evidence to another data source.
- No feature-importance view is presented as proof of factor effectiveness.
- `research_only=true`, `trade_ready=false`.

更多说明见 `docs/methodology.md`、`docs/product/frontend_artifact_studio.md`、`AGENTS.md` 和 `scripts/README.md`。
