# Legacy Web Retirement Policy

Status: **Completed — legacy server architecture remains retired**  
Original delivery: #317, #318, #319 and #320  
Current product boundary updated: 2026-08-12

## Decision that remains permanent

Alpha Engine 不恢复旧的 Web application server、REST backend、浏览器训练/回测、任务控制或 broker execution。

旧 Web 架构已经退出。浏览器仍然是一个只读研究与策略观察客户端；量化事实必须由 Python data / research / formal / operations pipeline 生成并通过受治理契约交付。

2026-08 的产品演化增加了一个重要区分：

- **Public Evidence Plane**：GitHub Pages/PWA 提供公开的正式历史证据；
- **Authenticated Current Operations Plane**：当产品策略声明当前 holdings / target / drivers 需要更高访问级别时，可以通过已有账户/entitlement 边界鉴权交付同一个 governed operations contract。

这不是恢复旧服务器产品。账户层只负责用户身份、entitlement 和受保护 current snapshot 的交付；模型、因子、回测、信号和证据计算仍不进入浏览器或账户服务。

## Current boundary

```text
Python data / research / formal / operations
                  │
        canonical repository evidence
                  │
        ┌─────────┴─────────┐
        ↓                   ↓
 Public Evidence Plane   Current Operations Plane
 GitHub Pages / PWA      authenticated entitlement
 historical evidence     governed current snapshot
        │                   │
        └─────────┬─────────┘
                  ↓
          read-only browser UI
```

- 历史证据边界：Formal Model Run Bundle v2；
- 当前决策事实：append-only Strategy Decision Ledger；
- 当前 UI read model：Strategy Operations；
- 稳定产品身份：`configs/strategies/registry.json`；
- 执行边界：Python CLI + maintained workflows；
- 产品状态：`research_only=true`、`trade_ready=false`。

## What was removed and stays removed

The 2026-08-02 retirement physically removed:

- browser-side training/backtest/system mutation UI;
- Python HTTP routers and temporary Web hosts;
- process managers, API containers, Compose and application-server runtime;
- endpoint-driven dashboard data paths;
- duplicated browser control planes;
- server host/port/CORS/application-runtime configuration.

这些能力不因为当前 operations 需要鉴权而恢复。

## Permanent rules

1. 浏览器不训练模型、不刷新 provider、不跑回测、不修改 research registry、不发订单。
2. 历史 market/backtest/factor evidence 必须来自版本化受治理成果，不从 authenticated API 另建第二份事实源。
3. 当前 operations 可以在 entitlement 验证后交付，但必须使用同一个 governed Strategy Operations contract；不得在浏览器或 Supabase 重写 signal logic。
4. 浏览器不从 OHLCV、positions 或图表反推 current target、execution price、PnL、factor statistic 或 operating health。
5. 新执行需求进入 Python domain/service/CLI；GitHub Actions 只负责编排 maintained entrypoint。
6. 缺失、不兼容、摘要漂移、access failure 或 evidence mismatch 必须显式 fail closed。
7. 不通过恢复本地/远程应用服务器解决前端需求。
8. 不增加 compatibility HTTP adapter、旧 endpoint fallback 或双数据源。
9. `qlib-dashboard/public/data/` 是构建 projection，不是 Git authority。
10. Strategy Operations 是 Decision Ledger 的 read model，不是独立事件数据库。

## Authenticated operations exception

Authenticated current operations is deliberately narrow:

Allowed:

- verify account session / entitlement;
- deliver a governed current Strategy Operations snapshot only after authorization;
- expose current holdings, target changes, current drivers and next-decision semantics according to Active Strategy Catalog policy.

Not allowed:

- execute model/factor logic in Supabase or browser;
- host historical formal evidence as a second database;
- silently fall back to a public snapshot when entitlement delivery fails;
- infer protected data from public historical traces;
- mutate research/formal evidence through the Web client.

## External protocol exception

MCP JSON-RPC remains an independent research protocol boundary. It does not host the frontend, become a browser runtime dependency, or justify restoring the retired application server.

## Enforcement

`scripts/check_legacy_web_boundary.py` and frontend account/access contract tests must continue to reject:

- retired server/process entrypoints;
- browser-side research mutation paths;
- endpoint fallback/data reconstruction;
- model-family access hardcodes that duplicate the Active Strategy Catalog;
- credentials or service-role material in browser assets.

## Final product truth

- **Historical Web evidence:** public GitHub Pages/PWA projection from canonical repository evidence.
- **Current operations:** governed read model; authenticated delivery only where the Active Strategy Catalog requires it.
- **Quantitative computation:** Python only.
- **Execution:** CLI / maintained workflows; no broker integration.
- **Local files:** browser local read only, no authoritative upload/sync path.
- **Scope:** research and strategy observation only; no trade authorization.
