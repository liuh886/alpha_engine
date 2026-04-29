# 交易辅助工具（Local-First）设计文档 v2.3

更新时间：2026-03-02  
角色视角：产品经理评估 + 架构师升级执行

---

## 1. 背景与目标

### 1.1 产品定位

本项目是一个 **本地优先（Local-First）** 的交易决策辅助系统，不做自动下单，聚焦“研究-回测-风控-复盘”闭环。

### 1.2 P0 目标

1. Agent 协同输出可解释的研究提案与风险结论。  
2. 数据更新、质量巡检、回测与报告链路可一键触发。  
3. UI 可用于演示与日常运营（模型、Arena、报告、数据状态）。  
4. 资产与元数据可追溯（`artifacts/` + SQLite metadata DB）。

---

## 2. 当前完成度评估（PM 视角）

### 2.1 结论摘要

- **总体完成度**：可运行、可演示，核心主链路已贯通。  
- **可交付判断**：在本轮架构修复后，达到“可路演”标准。  
- **主要风险**：历史测试基座仍引用旧版 `scripts/dashboard_server.py`，与当前 `api_server.py` 架构存在脱节。

### 2.2 模块完成度矩阵

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 多 Agent 业务层 | 已实现（可演示） | `src/agents/*` 与 `src/assistant/services/*` 已形成调用链 |
| 数据层 | 已实现（需持续治理） | 数据路由、质量检查、快照索引、作业编排已具备 |
| 交互层 | 已实现（本轮补关键接口） | React 控制台 + 多页面完成；补齐 job detail/stream/panic |
| 作业系统 | 已实现 | SQLite 持久化任务队列，支持异步执行与日志 |
| 路演稳健性 | 本轮增强 | 修复前端依赖的缺失 API，补 localhost 认证豁免 |

---

## 3. 总体架构（As-Is）

```text
[React + Vite Dashboard (qlib-dashboard)]
  |  /api/* + /artifacts/*
  v
[FastAPI API Server (api_server.py)]
  |
  +-- [Routers: data/models/arena/reports/backtest/chat/system/strategy]
  |
  +-- [Assistant Services]
  |     |- JobService (SQLite)
  |     |- Backtest/Training/Data/Model Service
  |
  +-- [Domain]
  |     |- Agents (alpha/risk/governance/router)
  |     |- Data (adapters/router/quality/neutralization/dim_reduction)
  |
  +-- [Storage]
        |- artifacts/* (dashboard json, reports, logs, models)
        |- artifacts/metadata/metadata.db
        |- data/watchlist/*
```

---

## 4. Agent 决策层设计

### 4.1 Alpha Agent

- 关注研究与策略生成，调用数据与回测工具完成提案。  
- 依赖中性化与质量检查结果，输出面向执行前的策略建议。

### 4.2 Risk Agent

- 负责风险审计和动态否决逻辑。  
- 对波动、情绪、历史风险案例进行裁决，形成 guardrail 约束。

### 4.3 Governance Agent

- 负责日常编排、异常处理与报告产出。  
- 将 Alpha 与 Risk 的冲突信息固化为可复盘证据。

---

## 5. 数据层设计（已补齐）

### 5.1 数据源与路由

- 入口：`src/data/router.py` 的 `MarketDataRouter`。  
- 能力：按市场策略（policy）在多个 adapter 间自动 fallback。  
- 输出：记录每次 provider 尝试结果（成功/失败/错误原因）。

### 5.2 质量与治理

- 质量引擎：`src/data/quality.py`。  
- 产物：按 market 生成 stale/csv missing/parse error 等指标与警告。  
- 快照：通过 `DataSnapshotIndex` / `DataQualityIndex` 入库（SQLite）。

### 5.3 特征工程保障

- 缺失值治理：`src/data/neutralization.py`（按 instrument 前向填充 + 中性填充）。  
- 降维：`src/data/dim_reduction.py`（PCA 保留主方差，降低过拟合风险）。

### 5.4 作业与持久化

- Job 编排：`src/assistant/job_service.py`，SQLite 持久化作业状态与命令。  
- 统一元数据库：`src/assistant/metadata_db.py`，WAL 模式。  
- 路径抽象：`src/common/paths.py`，支持 `TRADING_*` 环境变量覆盖。

### 5.5 对外交互（Data API）

- `POST /api/data/update`：异步触发数据更新作业。  
- `GET /api/data/status`：读取数据快照状态与质量告警。  
- `GET /api/data/snapshots/latest`、`GET /api/data/quality/latest`：快照与质量查询。  
- `GET /api/data/stock/{symbol}`：单标的 OHLCV 与风控信息。

### 5.6 当前风险与后续治理

- 需要进一步强化 `data_provenance` 的批次级落库与可视化追踪。  
- 部分质量报告依赖产物文件更新节奏，需增加调度 SLA 监控。

---

## 6. 交互层设计（已补齐）

### 6.1 前端结构

- 入口：`qlib-dashboard/src/App.tsx`。  
- 状态管理：Zustand（`globalStore.ts`）。  
- 页面：Control Center、Dashboard、Arena、Models、Reports、Data、Stock Terminal、Strategy。

### 6.2 核心交互流

1. 任务型交互  
- 从 UI 触发回测/数据更新/Arena 结算/报告导出。  
- 前端拿到 `job_id` 后轮询 `/api/jobs/{job_id}` 显示进度。

2. 实时日志交互  
- `LiveLogViewer` 使用 `/api/jobs/{job_id}/stream` SSE 拉取日志行。  
- 收到 `done` 事件后自动结束订阅。

3. Copilot 交互  
- `CopilotUI` 通过 `/api/agent/chat` 调用 Agent Router，返回 Markdown 格式回复。

4. 风险制动交互  
- 侧边栏 Panic 按钮调用 `/api/system/panic`，用于紧急中止运行态任务。

### 6.3 UI 数据契约

- 在线模式：`/api/*`。  
- 本地静态模式：`/artifacts/*.json`（模型、报告、数据状态等）。  
- 双模并存，支持演示与离线回放。

### 6.4 认证策略（本轮修复）

- API 基于 Basic Auth。  
- 本轮新增 localhost 信任豁免（`TRADING_UI_TRUST_LOCALHOST`，默认开启），保证本地 UI 与 SSE 无额外认证阻塞。  
- 非 localhost 仍走用户名/密码校验。

---

## 7. 验收标准（可交付、可路演）

### 7.1 功能验收项

1. Dashboard 各主页面可进入并渲染。  
2. Copilot 可发起对话并返回内容。  
3. 数据/回测/Arena/报告相关任务可创建并可查询状态。  
4. 实时日志流接口可被前端消费。  
5. Panic 开关可触发运行任务熔断标记。

### 7.2 路演标准

- 无需手工改代码即可本地拉起前后端并完成演示主路径。  
- 关键操作均有可视反馈（状态、日志、结果页面）。  
- 风险告警与“非自动交易”边界表达明确。
- 能够基于真实数据展示模型训练操作、模型训练与回测结果，Dashboard 可解析回测结果并对比不同模型特征，从而指导交易实战。  
- Agent 通过各类脚本具备治理能力，能够日常自持，并在持续演进中控制系统复杂度。

### 7.3 本轮验收结果

1. 无头浏览器跨页面巡检通过：Control Center、Dashboard、Data、Models、Arena、Reports、Stock Terminal 均可访问并渲染。  
2. Copilot 交互通过：已在页面中收到 `AgentRouter Dispatch: AlphaAgent` 回复。  
3. 作业链路通过：`/api/system/exec` 创建任务成功，`/api/jobs/{id}` 可查询终态，`/api/jobs/{id}/stream` 可输出日志与 `done` 事件。  
4. 治理操作通过：`/api/system/panic` 可执行并返回熔断统计。  
5. 关键缺陷闭环：`StockTerminal` 图表 API 兼容性问题已修复，复测后前端控制台无错误。

---

## 8. 结论

v2.3 版本已将原先空白的“数据层/交互层”落为可实现、可验证、可演示的设计描述，并完成本轮 P0 架构修复。  
下一步重点是清理历史测试基座与遗留 API 契约差异，进一步提升工程一致性与回归稳定性。
