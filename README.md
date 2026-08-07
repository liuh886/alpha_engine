# Alpha Engine V2

## 受治理的中频系统化策略研究与运行观察平台

Alpha Engine 用固定研究契约、时间有效的数据、walk-forward / prospective 验证和 fail-closed 决策，把候选研究收敛成可审计的正式策略，并把正式回测、当前策略状态、研究证据和后续迭代连成一条链。

> **Current status — 2026-08-08**
>
> - Alpha Engine 仍是 `research_only=true` 的研究与策略观察系统，不提供 broker/order execution。
> - GitHub Pages/PWA **Strategy Console** 是公开 Web 产品；Python CLI、脚本和 GitHub Actions 负责数据、训练、回测、研究和信号生产。
> - 正式模型目录当前包含 QQQ Rotation v4.2、US x1.1、CN x1.1 和 BYD v1.2。
> - QQQ/BYD 已有受治理的运行证据来源；US/CN 的 10-session live signal publication 由 Issue #600 继续闭环，在此之前前端明确显示 signal unavailable，而不是从历史回测推断实时持仓。
> - Model Run Bundle v2 是正式历史证据边界；Alpha Research Loop receipts 是研究迭代边界；Strategy Operations contract 是当前状态的前端语义边界。

公开入口：<https://liuh886.github.io/alpha_engine/>

产品架构说明：[`docs/product/strategy_console.md`](docs/product/strategy_console.md)

## 1. Strategy Console

前端从“按仓库子系统浏览证据”收敛成“按正式策略阅读决策”。一级导航只有：

- **Overview** — Strategy Fleet：当前状态、target、变动、next decision、风险与运行状态；
- **Strategies** — 正式策略列表和单策略工作空间；
- **Research** — Runs / Compare / Decisions / Factors / Reports，用于解释策略如何演化；
- **System** — Data / Library / Methodology，用于检查数据、freshness 和证据边界。

单策略阅读顺序是：

```text
Now
  -> Performance / Risk / Holdings / Trades / Attribution
  -> Current Drivers
  -> Evidence / Lineage
```

浏览器不会从历史 backtest 重建“当前仓位”。缺少正式 signal pipeline 时必须显式失败或显示 unavailable。

## 2. 证据架构

```text
ResearchSpec / Factor definitions
        ↓
Python data / model / backtest / signal pipelines
        ↓
┌──────────────────────────────────────────────────┐
│ Formal Model Run Bundle v2                      │
│ performance / risk / portfolio / trades /       │
│ attribution / robustness / lineage              │
└──────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────┐
│ Strategy operations evidence                    │
│ state / current / target / delta / cadence /     │
│ freshness / delivery / current drivers          │
└──────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────┐
│ Alpha Research Loop receipts                    │
│ hypothesis / identities / windows / gates /      │
│ verdict / learning                               │
└──────────────────────────────────────────────────┘
        ↓
GitHub Pages / installable PWA / local bundle reader
```

原则：

- Python 研究流水线是事实来源；
- 浏览器永久只读，不训练、不刷新模型、不修改 registry、不下单；
- 正式 Bundle v2 的 manifest / section / SHA-256 不匹配时 fail closed；
- 当前 signal、execution evidence 和历史 backtest 语义分离；
- stale / blocked / unavailable 必须显式显示；
- 因子定义与因子观测分离，Issue #626 负责把 canonical factor identity / freshness / current drivers 贯通到正式模型和前端。

## 3. 当前正式策略

| Strategy | Kind | Decision cadence | Current frontend operations |
| --- | --- | --- | --- |
| QQQ Rotation v4.2 | rules-based allocation | daily close evaluation | governed operating ledger |
| US x1.1 | cross-sectional ranker | 10 trading sessions | signal pipeline unavailable until #600 closes |
| CN x1.1 | cross-sectional ranker | 10 trading sessions | signal pipeline unavailable until #600 closes |
| BYD v1.2 | rules-based allocation | daily eligible close evaluation | governed BYD signal ledger / awaiting valid observation when empty |

这四个策略是独立正式策略。仓库目前没有定义跨 QQQ / US / CN / BYD 的统一资本配置合同，因此前端不会虚构一个总组合权重。

## 4. US / CN 10D 研究契约

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

研究执行绑定到 `configs/research_paradigms/` 中的版本化规范。基准日期、股票池、provider lineage、因子身份、覆盖证据或最小窗口缺失时均 fail closed。

## 5. 安装研究环境

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

## 6. 常用研究与发布命令

```text
make doctor           检查 Python 研究环境
make data             更新市场数据
make train-us         运行 US 训练流程
make train-cn         运行 CN 训练流程
make backtest         运行标准回测流程
make research-bundle  导出版本化研究成果包
make static-pwa       构建静态 Strategy Console PWA
make breakfast        生成每日研究简报
make ci               运行仓库质量门禁
```

正式回测刷新通过 catalog-driven reviewed refresh transaction 延伸已接受证据，不重开模型选择，也不自动合并数据更新。

## 7. 前端开发与验证

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

前端继续使用现有 React + Vite + TypeScript + Radix/Tailwind + lightweight-charts/Recharts + Vitest/Playwright 技术栈，不为了“现代化”引入第二套框架或后台服务。

## 8. Scope and safety

- No browser-side model training.
- No broker integration or order execution.
- No automatic model promotion.
- No hosted upload or cloud synchronization of local bundles.
- No silent fallback from missing artifact evidence to another data source.
- No inferred live position from historical backtests.
- No feature-importance view is presented as proof of factor effectiveness.
- `research_only=true`, `trade_ready=false`.

更多说明见 `docs/product/strategy_console.md`、`docs/methodology.md`、`docs/architecture/legacy_web_retirement.md` 和 `AGENTS.md`。
