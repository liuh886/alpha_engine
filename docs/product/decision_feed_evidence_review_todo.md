# Decision Feed + Evidence Review — 轻量实施 TODO

**基线**：`main@e14c57838`（2026-10-27）。**当前状态（2026-10-31）**：Decision Feed 的三重点呈现已实现；Evidence Review 与 P1 研究身份映射仍待各自验收。原规划基线保留，不代表完整产品 GO。

2026-10-28 收口：本文以现行 [Strategy Console 合同](strategy_console.md)
和 [AGENTS.md](../../AGENTS.md) 为权威。上述 SHA 是计划编写基线，
不是当前 main 或后续实现的验收 SHA。

## 本文档的验收与后续实施边界

- [x] 任务绑定现有页面、reader 与正式身份；不新增数据或信号权威。
- [x] 明确研究、当前授权读取与公开历史证据的区别，保留四策略完整 fleet。
- [x] 以下 P0/P1 和界面验收均是后续 implementation PR 的待办，
  不表示本文档 PR 必须包含实现才可收口，也不表示已经交付。

后续依次提交两个小 PR：先原位完成 Decision Feed，再完成正式证据的
Evidence Review；每项以最终提交、测试和截图验收。P1 研究关联仅在身份
映射、权限和脱敏摘要具备时实施。#1288 独立约束敏感公开面；这份文档
不扩大该公开面，不以其他研究 PR 或整个赛马场 UI 完成为前提。

## 产品目标

用户打开 Alpha Engine，应当在**同一条日常阅读路径**里回答：

1. 今天有什么变化、风险或待处理状态？
2. 哪些可验证证据支持或反对当前判断？
3. 下一次应当**观察 / 复核 / 等待**什么，哪些事情尚不具备行动依据？

研究证据只能**辅助解释**；未经治理验证的研究收据不能生成或替代正式交易信号。

## 最小交互（现有页面，不新增主导航）

```text
/app  —  Today: what matters?
  [需要关注的事项，最多 3 条：策略 + 日期 + 状态 + 一句话原因]
      → 查看证据 → /strategies/:strategyId
  [现有四策略完整列表、状态与历史表现保留]

/strategies/:strategyId — Why / Why not / Next
  当前正式状态与原有模型目标
  支持证据 | 反证 / 阻断 | 解释局限
  下一次允许的复核步骤 + 数据截止日期
  已验证研究来源链接（没有明确绑定时显示“尚无关联研究证据”）
```

**不做**：新 Research Studio / 新一级菜单、聊天建议生成器、交易按钮、新后端/DB/调度、自动持仓指令、由研究收益推导买卖方向。

## 后续 implementation PR 的 TODO（按顺序，一个轻量实施闭环）

- [x] **P0 · Decision Feed** — 原位精简 `qlib-dashboard/src/components/DailyResearchBrief.tsx`：利用已有 `describeStrategyObservation()` 的 `kind/reason/nextStep` 与正式策略快照，对 `changed → attention → retained → unchanged` 等状态排序；顶部最多突出 **3 条**，无变化时直接说明“无新动作”；完整四策略列表保留在 `StrategyFleet`。每条信息显示 cutoff/状态/原因，点击进入现有策略详情。避免新增一套信号计算。
- [ ] **P0 · Evidence Review** — 原位完善 `qlib-dashboard/src/pages/StrategyDetailPage.tsx` 的 `Research tracking assessment`：复用 `loadDecisionForRun()` 的**已验证** `gates / supporting_evidence / contradictory_evidence / interpretation_limits / next_permitted_validation_step`，按「支持 / 反证 / 局限 / 下一步」呈现。pending、blocked、absent、error 显示真实含义；不可把 `supported` 翻译为“建议买入”。
- [ ] **P1 · 研究与策略的只读关联** — 优先复用既有 `research_study` 收据和 Model Run Bundle v2 的明确身份；只有存在**可审计的研究→正式模型映射**以及可授权读取的脱敏摘要，才在证据区域加研究入口。否则维持“尚无关联研究证据”，研究结果继续留在本地 CLI；**不自动复制本地收据到公共 Pages**，不按股票代码猜测关联。#1288/A4 FAIL 未关闭前禁止扩大敏感公开面。
- [ ] **验收与收口** — 扩充**现有** React 单测 / Playwright 检查：变化、无变化、过期、数据阻断、缺证据、无权限、研究未认证、移动端 375px；验证点击详情保持身份与日期正确、没有新发单入口或隐私字段。记录测试结果、截图、commit 和阻断事实，再标记完成。

## 数据与界面唯一权威

| 需求 | 读取已有实现 | 禁止做什么 |
| --- | --- | --- |
| 今天有什么变化 | `strategy-operations.ts` + `DailyResearchBrief.tsx` | 浏览器自行预测信号或拼凑当前仓位 |
| 为什么有此判断 | `model-run-decision.ts`（bundle/hash/gates 验证） | 从未审查的绩效推导 `supported` |
| 策略背景与模型目标 | `StrategyDetailPage.tsx` + 现有授权读链 | 把模型 target 当作账户实际持仓 |
| 历史研究成果 | `alpha research study show` 的本地收据 | 原始 JSON 直接公开、把 research-only 升为 trade-ready |

**完成定义**：用户在 `/app` **不超过两次点击**，能看到事项的证据、反证、时间与下一步；无有效证据时，页面明确说**不能得出交易结论**。不以新增 UI 数量或策略收益作为成功标准。

## 2026-10-31 Decision Feed 实现

沿用既有观察 reader 和稳定排序，仅突出最多三条；状态汇总仍覆盖完整四策略，
并明确提示剩余策略位于完整 Fleet。只有全部观察都已验证为 unchanged/within-cadence
retained 时才显示无新模型变化；pending/access/attention/空数据不作该声明。
完整 Fleet、Status 四策略、身份拒绝与 source-read 去重均保留。此实现不新增
排序计算权威、模型、导航或当前信号。Evidence Review/P1/整体产品门禁未因此关闭。
