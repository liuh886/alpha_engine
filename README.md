# Alpha Engine V2

## 受治理的中频系统化策略研究与运行观察平台

Alpha Engine 用固定研究契约、时间有效的数据、exact replay / walk-forward / prospective 验证和 fail-closed 决策，把候选研究收敛成可审计的正式策略，并把“模型为什么存在”和“模型现在为什么这样做”连成一条证据链。

> **Current status — 2026-08-13**
>
> - Alpha Engine 仍是 `research_only=true`、`trade_ready=false` 的研究与策略观察系统，不提供 broker/order execution。
> - `configs/strategies/registry.json` 是当前正式策略与 active model 身份的唯一产品权威；README 不复制 active model version 列表。
> - Model Run Bundle v2 是正式历史证据边界；append-only Strategy Decision Ledger 是当前决策事实边界；Strategy Operations 是由二者生成的只读当前状态投影。
> - GitHub 不再跟踪 `data/research/strategy_operations/` 或 `qlib-dashboard/public/data/`；它们在 CI / Pages 构建时由 canonical evidence 重新生成。
> - 历史正式证据公开；当前策略 operations 的访问级别由 Active Strategy Catalog 声明，账户/entitlement 只负责判断用户是否满足该级别。

公开入口：<https://liuh886.github.io/alpha_engine/>

产品架构说明：[`docs/product/strategy_console.md`](docs/product/strategy_console.md)

## 1. Strategy Console

Strategy Console 按“用户要回答的问题”组织，而不是按仓库子系统组织：

- **Overview** — Strategy Fleet：正式策略、历史绩效、当前状态与运行健康；
- **Strategies** — 单策略工作空间：Performance / Risk / Holdings / Trades / Attribution / Drivers / Evidence；
- **Research** — Runs / Compare / Decisions / Factors / Reports，用于解释模型如何演化；
- **System** — Data / Library / Methodology，用于检查数据、freshness 和证据边界。

浏览器不会从历史 backtest 推断当前仓位，也不会重算模型、因子、PnL 或成交价。缺失的 current evidence 必须显式显示 unavailable / blocked。

## 2. Strategy-centered authority

```text
                         Active Strategy Catalog
                                  │
                    ┌─────────────┴─────────────┐
                    ↓                           ↓
               Data contracts              Model logic
                    │                           │
                    └─────────────┬─────────────┘
                                  ↓
                            Research engine
                                  ↓
                        Immutable Model Run
                         Model Run Bundle v2
                                  │
                    ┌─────────────┴─────────────┐
                    ↓                           ↓
             Formal identity                 Decision Ledger
                    │                           │
                    ↓                           ↓
             Formal catalog            Strategy Operations
                    │                           │
                    └─────────────┬─────────────┘
                                  ↓
                           Strategy Console
```

`strategy_id` 是稳定产品身份；`model_version_id` 是可以被正式晋级替换的实现身份。一个稳定 strategy 可以切换到新的 accepted model version，而 URL、权限语义、operations 家族和产品理解不需要复制一套新系统。

## 3. Evidence 与 Decision Ledger

Model Run Bundle v2 保存已观察、可复核的历史证据：

- performance / risk；
- portfolio / trades / attribution；
- robustness；
- diagnostics；
- lineage。

当前策略决策保存为 append-only decision evaluation：

```text
Evidence cutoff
    ↓
Decision / target
    ↓
Delivery / workflow identity
    ↓
Execution / outcome evidence when available
```

Strategy Operations 不是新的事实源，而是：

> Active Strategy Catalog + Formal Catalog + latest valid Decision Ledger → current read model

因此它可以随时重建，不应该作为独立数据库长期维护。

## 4. 当前正式策略

当前 stable strategy 集合与 active model version **只从 `configs/strategies/registry.json` 读取**。README 不维护第二份 active-model 表。

目前产品围绕四个稳定 strategy family 组织：

- `qqq_rotation` — rules-based allocation；
- `us_x` — US cross-sectional ranker；
- `cn_x` — CN cross-sectional ranker；
- `byd` — BYD rules-based allocation。

它们是独立研究策略。仓库没有定义跨 QQQ / US / CN / BYD 的统一资本配置合同，因此前端不会虚构总组合权重。

## 5. Public Evidence Plane / Current Operations Plane

### Public Evidence Plane

Git-reviewed、不可变、可复核：

- formal identity；
- historical performance / risk；
- historical holdings / trades / attribution；
- methodology / lineage / research reports。

GitHub Pages 在构建时从 canonical repository evidence 生成静态 projection。

### Current Operations Plane

只承载当前状态：

- current / target allocation；
- latest decision；
- current drivers；
- next decision semantics；
- delivery / operating health。

访问级别由 Active Strategy Catalog 声明。需要 Pro 的 current operations 必须经过 authenticated entitlement delivery；不能靠前端隐藏公开 JSON 伪装成权限控制。

量化计算仍然由 Python pipeline 完成；Supabase/账户系统不是 market/backtest/factor 数据库。

## 6. US / CN 10D 研究契约

| Property | Contract |
| --- | --- |
| Forecast horizon | 10 trading sessions |
| Holding period | 10 trading sessions |
| Rebalance cadence | 10 trading sessions |
| Economic return | governed raw holding-period return |
| Execution | explicit one-session delay where declared by the formal model |
| Training/evaluation boundary | processed rank labels for fitting; raw returns for economics |
| Validation | frozen window roles + embargo + exact incumbent replay |
| Benchmark | CSI 300 for CN; QQQ for US |
| Scope | `research_only=true` |

研究执行绑定到版本化 mission/spec、provider/component identity、universe、factor、cost 和 evaluator contract。任何关键身份或 replay 不一致都 fail closed；不得用 fallback 数据或简化 evaluator 让候选通过。

## 7. CLI 是执行入口

Alpha Engine 使用 Astral `uv`，`uv.lock` 是 Python 依赖来源：

```bash
git clone https://github.com/liuh886/alpha_engine.git
cd alpha_engine
uv sync --extra dev
```

主要治理入口：

```text
alpha data ...                 数据准备与 readiness
alpha research ...             研究、replay、run import
alpha ops record-decision ...  追加不可变策略决策
alpha ops build ...            生成 Strategy Operations read model
```

GitHub Actions 负责调度这些 maintained entrypoints；领域逻辑不应只存在于 workflow YAML。旧 wrapper 一旦被 `alpha` 入口替代就直接删除，不保留 compatibility alias。

常用质量门禁：

```bash
make doctor
make test
make ci
```

## 8. Formal publication

正式回测刷新是 catalog-driven reviewed transaction：

1. provider / component evidence fail closed；
2. exact incumbent replay gate；
3. 生成或延伸 governed formal source / native Bundle v2 evidence；
4. Active Strategy Catalog 决定最终 active formal set；
5. 生成唯一 Bundle v2 formal catalog；
6. review PR 只提交 canonical evidence；
7. Strategy Operations 与前端 `public/data` 在验证/部署时重新生成。

当前 US ranker 已使用 native Bundle v2 publication path；被取代的 model version 不再参与 active formal refresh。不存在 v1→v2 migration reader、projector registry 或 browser fallback。

## 9. 前端开发与验证

```bash
uv sync --frozen
uv run alpha ops build --generated-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
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

前端继续使用 React + Vite + TypeScript + Radix/Tailwind + lightweight-charts/Recharts + Vitest/Playwright；不为了“现代化”引入第二套框架或浏览器计算后端。

## 10. Scope and safety

- No browser-side model training or evidence reconstruction.
- No broker integration or order execution.
- No automatic model promotion.
- No silent fallback from missing governed evidence.
- No inferred live position from historical backtests.
- No frontend-generated execution price, PnL, factor statistic or system-health claim.
- No second active-strategy registry.
- No committed generated frontend projection as a fact source.
