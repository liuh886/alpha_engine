# Alpha Engine 工作实施计划 (Work Plan)

> 目标：将 Alpha Engine 从 86% 完成度推进至 100% 全面就绪。
> 原则：遵循 `research_only=true` / `trade_ready=false`，严格执行数据不可变性、证据闭环与 fail-closed 门禁。

---

## 阶段规划概览

| 阶段 | 周期/优先级 | 核心目标 | 产出物与交付标准 |
|---|---|---|---|
| **Phase 1** | P0 (当前冲刺) | **前端多策略观察台转正交付** | 将 `docs/prototypes/strategy-observer` 原型功能转正为生产组件，完成与 `strategy_operations` 2.2.0 数据读取合同的对接与 E2E 验证。 |
| **Phase 2** | P0 (关键攻坚) | **选定池数据面闭环 (Issue #324, #325)** | 完成 US 87 Alpaca VWAP 验证与 `us_selected_alpha158_v1` 解锁；完成 US 87 SEC PIT 基本面扩展与 CN 130 事件数据全量审计。 |
| **Phase 3** | P1 (运营集成) | **模型运营闭环与纸面账本联调 (T47.8)** | 将 T47.1~T47.7 后端能力（Champion/Challenger、漂移监控、模拟账本、再训练决策）暴露在前端/CLI，形成完整监控面板。 |
| **Phase 4** | P1 (科研推进) | **新一代信息集模型训练与前瞻证据跟踪** | 在解封的宽池因子/基本面数据面上开启新一代模型实验；持续封存 5 条基线策略的实盘阴影追踪证据。 |

---

## 详细任务拆解 (Checkable Steps)

### Phase 1: 前端多策略观察台转正交付 (Frontend Observer Consolidation)
- [x] **1.1 合同与字段审计**：核查 `src/artifacts/strategy_operations.py` (v2.2.0) 产出的 `allocations`、`signal`、`execution` 字段语义，确认增配/减配/保持方向与时效判定逻辑。
- [x] **1.2 生产组件迁移与重构**：
  - [x] 重构 `qlib-dashboard/src/components/StrategyFleet.tsx`，将独立 HTML 原型的市场筛选、信号筛选、周期切换整合为生产组件。
  - [x] 新增 `StrategySignalDrawer.tsx`，支持目标配置对比、时效判定、证据展开与移动端 Bottom Sheet 抽屉展示。
  - [x] 确保无有效目标时如实显示“First target / no prior comparison record”，严禁假定零仓位或前端补零。
- [x] **1.3 数据同源性与回退机制**：严格遵循 `docs/frontend-refresh-spec.md`，区分文档级失效与记录级失效，缺失指标展示真实 `Unavailable`，走势图统一坐标与口径。
- [x] **1.4 自动化测试与浏览器验收**：
  - [x] 编写 `StrategySignalDrawer.test.tsx` (4 tests) 与 `StrategyFleet.test.tsx` (4 tests)，全套 Vitest 41 个测试文件 152 项测试全绿。
  - [x] 运行 Playwright 桌面、平板、移动端 12 项 E2E 走查测试，全部通过；生产构建 `npm run build` 打包成功无告警。

### Phase 2: 选定池数据面就绪攻坚 (Data Plane Readiness: #324 & #325)
- [x] **2.1 US 87 规范化 VWAP 与 Alpha158 解封 (Issue #325)**：
  - [x] 审查 `scripts/data/build_canonical_vwap_provider.py` 的 US 市场 Alpaca 请求通道与 SIP/OTC 映射契约（默认 SIP，ABBNY/SBGSY 走 OTC）。
  - [x] 严格遵循治理合同：无 live APCA 凭证时 fail-closed 保持 `us_selected_alpha158_v1` blocked 状态，绝不引入伪造/合成 VWAP；CN 选定池 `cn_selected_alpha158_v1` 已全量实例化并就绪。
- [x] **2.2 US 87 PIT 基本面扩展 (Issue #324)**：
  - [x] 修复 SEC EDGAR 403 爬虫拦截，并扩展 `companyfacts_to_events` 支持 `us-gaap` 与 `ifrs-full` 双准则及多币种（EUR/TWD 等），打通外资 ADR 抽取。
  - [x] 运行 `populate_selected_pool_events.py --market us` 抽取 71,351 条 PIT 基本面事件与 3,244 条企业行为，全量覆盖 86 家在册实体（`SBGSY` 受治理豁免）。
  - [x] 运行 `scripts/data/audit_fundamental_coverage.py --market us` 通过 100% PIT 时效门禁（`available_at >= reported_at`），解锁 `us_selected_price_plus_fundamentals_v1` 训练配置（`ready`）。
- [x] **2.3 CN 130 事件数据全量审计 (Issue #324)**：
  - [x] 统一 CN 130 财报公告、分红送转与复权因子的事件源（Sina/CNINFO/EastMoney）。
  - [x] 确认排除退市与终止标的 (`600837`, `601989`)，企业行为覆盖率 100%（130/130），基本面覆盖率 99.2%（129/130，仅新股 301666 尚未披露）。
- [x] **2.4 数据就绪门禁验证**：
  - [x] 运行 `scripts/dump_bin.py` 与 `create_universes.py` 编译本地 Qlib 二进制特征库。
  - [x] 运行 `python scripts/check_multi_market_data_readiness.py --alignment-mode auto`，两地市场全部通过验证（US 保留 74 标的，CN 保留 55 标的，`ready_markets: ['us', 'cn']`，`skipped: []`）。

### Phase 3: 持续模型运营闭环 (Continuous Model Operations - T47.8)
- [x] **3.1 运营数据物化与读取契约 (Model Operations Materialization & Contract)**:
  - [x] 实现 `src/artifacts/model_operations.py`：统合 T47.1 Champion、T47.2 漂移监控、T47.3 执行计划、T47.4 纸面账本、T47.5 归因、T47.6 运营门禁与 T47.7 再训练策略，物化为不可变 `operations_summary.json` (schema: `model_operations_v1`)。
  - [x] 在 `src/cli/main.py` 的 `alpha ops` 中新增 `model-ops` 命令，支持 CLI 生成与检查运营状态。
  - [x] 编写并运行 `tests/test_model_operations_artifact.py`，保证数据物化与哈希链完整性（4/4 测试通过）。
- [x] **3.2 前端/控制台看板集成 (Model Operations Frontend Console)**:
  - [x] 在 `qlib-dashboard/src/lib/model-operations.ts` 中实现不可变数据解析器与 fail-closed 容错校验。
  - [x] 在 `qlib-dashboard/src/pages/ModelOperationsPage.tsx` 实现模型运营控制台视图（Champion/Challenger、漂移监控、运营门禁决策、纸面账本回放与执行归因）。
  - [x] 在 `qlib-dashboard/src/routes.ts` 注册 `/model-operations` 路由并在 `SystemHubPage.tsx` 挂接导航入口，通过 `npm test`（157/157 全绿）、`check-ui-language.mjs` 与 `npm run build`。
- [x] **3.3 操作演练与防线熔断验证 (Fail-Closed Gate Proof)**:
  - [x] 编写并执行端到端演练测试 `tests/test_t47_operator_e2e.py`（5/5 测试通过），模拟严重漂移与风控触发，实证门禁自动拒绝生成高风险执行计划（`plan_eligible=False`），正式关闭 T47.8。

### Phase 4: 科研模型演进与前瞻证据跟踪 (Model Research & Shadow Evidence)
- [x] **4.1 开启基于扩展数据面的模型训练**：
  - [x] 冻结新的研究范式配置，引入 Alpha158 宽表与 PIT 基本面因子组合（`cn_selected_alpha158_fundamentals_v1`）。
  - [x] 运行 Walk-forward 交叉验证并产出不可变 `ModelArtifact` (`cd205728823540caa9ea93dc248d5685`)、重构检验通过（100% 相关度），不可变实验收据归档。
- [x] **4.2 日常前瞻证据自动维护**：
  - [x] 保持 5 条正式基线策略（QQQ v4.3, US x1.3, CN x1.2, CN_27 v1.3, BYD v1.3）的交易日决策封存与 Delivery Receipts 交付（`alpha ops build` 5/5 全量通过）。
  - [x] 监控 CI 工作流状态，确保存储与计算预算始终控制在 45 个工作流配额之内（CI 治理审计 0 违规）。
  - [x] 生成 Release Candidate (`rc_20260918`)，28 项密码学/结构校验全部通过。
  - [x] 运行发布门禁 `release_gate.py`，全套 10 项本地/CI 质量门禁全绿通过（Ruff, Mypy, 3,774 项后端测试 0 失败, npm ci, tsc, eslint, 157 项 Vitest, 前端生产构建, Playwright 浏览器测试, uv 轮子打包），产出权威裁定 `release_gate_verdict.json`。

---

## 阶段验收与复盘 (Review Section)
- [x] **Phase 1 验收标准**：前端生产构建无报错，Vitest 41 个文件 152 项测试全绿，Playwright 12 项多设备测试通过，Observer 视图完整展示真实策略状态与信号抽屉。 ✅ 2026-09-17
- [x] **Phase 2 验收标准**：US 87 与 CN 130 两大选定池全部通过 `check_multi_market_data_readiness` 门禁（`ready_markets: ['us', 'cn']`），PIT 基本面（71,351 条记录）与企业行为（3,244 条记录）全量审计通过，`us_selected_price_plus_fundamentals_v1` 训练画像解封为 `ready`。 ✅ 2026-09-18
- [x] **Phase 3 验收标准**：T47.8 任务正式关闭，不可变模型运营读模型物化与控制台上线，纸面账本 SHA-256 哈希链严密验证，归因分解在容差内严密闭环，全套 162 项 T47 后端测试与 157 项前端测试全绿。 ✅ 2026-09-18
- [x] **Phase 4 验收标准**：产出带哈希签名的权威候选报告（ReleaseCandidate `rc_20260918`），通过 `release_gate.py` 完整验证，全系统 10 项发布质量门禁全部通过（包含 3,774 项后端测试与浏览器 E2E 测试），闭环交付 `release_gate_verdict.json`。 ✅ 2026-09-18

