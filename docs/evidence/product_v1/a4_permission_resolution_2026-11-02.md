# Gate A4 / A3 权限缺口治理与事实裁定 (Permission Policy Resolution)

- **基准日期**: 2026-11-02
- **归属工单**: Gate A4 / Gate A3 / Issue [#1279](https://github.com/liuh886/alpha_engine/pull/1279) / Issue [#1288](https://github.com/liuh886/alpha_engine/issues/1288)
- **执行原则**: 恪守 `research_only=true` / `trade_ready=false`，严格区分代码/SQL 源码声明与真实生产已部署状态，严禁为验收在生产环境中伪造测试账号或临时修改生产权限策略，维持客观事实与 Fail-closed 铁律。

---

## 1. 四策略权限策略权威对账：源码声明 vs 真实生产已部署状态

对 `configs/strategies/registry.json`、历史数据库迁移 `supabase/migrations/` 与 **生产真实抓取证据** [`accountless_access_observation_2026-10-31.json`](file:///D:/Documents/GitHub/alphaengine/docs/evidence/product_v1/accountless_access_observation_2026-10-31.json) 进行端到端对账，事实矩阵如下：

| 策略 ID | 策略展示名 | 历史证据权限 (`registry.json`) | 历史源码迁移声明 (`20260812022634`) | **真实生产已部署策略 (`2026-10-31` 观测)** | 匿名只读访问实际行为 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`byd`** | BYD v1.3 | `public` | `public` | **`public`** | 允许匿名只读查看历史与运行快照 |
| **`cn_27`** | CN_27 V1.3 | `public` | `public` (20260908) | **`public`** | 允许匿名只读查看历史与运行快照 |
| **`us_x`** | US x1.3 | `public` | `public` | **`public`** | 允许匿名只读查看历史与运行快照 |
| **`qqq_rotation`** | QQQ Rotation v4.3 | `public` | `pro` | **`public`** | 允许匿名只读查看历史与运行快照 |
| **`cn_x`** *(退役)* | CN x1.2 *(已退役)* | *(不在 registry)* | `public` | **`public`** *(待 Owner 迁移清理)* | 仍可匿名只读访问旧快照 |

### 核心权限架构与事实澄清
1. **静态证据面 (Historical Evidence)**：
   - 四大策略在 GitHub Pages 静态分发层均为 `historical_evidence_access: "public"`。
   - 经过 `sync-formal-model-runs.mjs` 脱敏后，完全剥离了敏感 `operating_state` 与目标权重，作为公开研究透明度资产提供。
2. **源码声明与生产实际状态的脱节澄清**:
   - 历史源码迁移 `20260812022634_alpha_engine_strategy_access_policies.sql` 曾声明 `qqq_rotation: pro`；
   - **但在生产环境数据库中，实际部署的策略快照记录证明 `qqq_rotation required_tier = public`**（见 `accountless_access_observation_2026-10-31.json` 行 93）；
   - 因此，**源码中带 `pro` 的历史迁移并不能作为生产部署状态的证明**。在生产现场，当前全部 4 大活跃策略均为 `public`，完全对齐单人量化工作站（ADR-0003）的只读公开透明度定位；
   - 若未来需要将 `qqq_rotation` 正式限制为 `pro`，必须通过专门的、经 Owner 批准并带回滚方案的独立迁移，并在具备真实测试账号时执行完整的授权/拒绝测试。当前系统如实记录生产环境状态为 `public`。
3. **严格 Fail-closed 默认安全基线**:
   - 若任何策略未在 `product_access_policies` 中显式声明，`resolveRequiredTier` 会确定性回退至 `'owner'` 级别；
   - 数据库 RLS 函数 `has_product_tier_access` 对缺失策略行直接拒绝访问，绝不静默放行。

---

## 2. 真实授权、拒绝与撤权行为核验 (合规边界与禁止伪造声明)

根据指令要求：“先确定四策略当前状态究竟采用何种权限策略，再验证真实授权、拒绝和撤权行为，不要为了验收虚构测试账户或改变生产权限。”

### 核验结果与客观记录：
1. **真实公开/授权访问**:
   - 在生产 Pages 部署 (`f97d8b5507`) 与生产数据库中，由于 4 大活跃策略均为 `public`，匿名用户与认证用户均能正常读取脱敏证据与运行快照（36 formal sections verified，0 violations）。
2. **受保护行真实拒绝测试 (Protected Row Rejection)**:
   - **真实状态**: **NOT_TESTED: no non-public strategy policy in observed production configuration**。
   - **原因**: 生产环境中 4 大活跃策略均为 `public`，系统中当前不存在非 public 的生产策略行，因此无法在线上生产验证“未授权匿名访问非 public 策略被确定性拒绝”；代码层面的 RLS 拒绝逻辑已由单元测试覆盖。
3. **真实会话过期/撤权测试 (Entitled / Denied / Revoked Real Sessions)**:
   - **真实状态**: **NOT_TESTED: operator reports no dedicated test account/session**。
   - **原因**: 生产环境中未配置独立的非生产专用测试账号（如专用 Pro / Free / Expired 测试账号）。我们严格恪守安全铁律，**绝不在生产中伪造测试用户、绝不在生产中篡改已有权限策略**。在没有真实受限测试凭据前，**门禁 A4 绝不标记为 PASS**。

---

## 3. 快照发布完整性校验与安全修剪闭环 (P0 安全修复)

针对此前发布的 Edge Function 存在的“部分提交导致误删活跃策略”的严重隐患，本次 PR 完成了服务端防御性架构加固：

1. **服务端前置契约强校验 (`supabase/functions/alpha-engine-publish-strategy-operations/index.ts`)**:
   - 显式声明不可变活跃策略及其模型版本白名单：
     ```typescript
     const AUTHORIZED_ACTIVE_STRATEGIES: Record<string, string> = {
       byd: "byd_v1_3_recovery_event_low_vol_confirmation_v1",
       cn_27: "cn_27_v1_3",
       qqq_rotation: "qqqi_qqq_tqqq_v4_3",
       us_x: "us_x1_3",
     };
     const RETIRED_ALLOWLIST_STRATEGY_IDS: readonly string[] = ["cn_x"];
     ```
   - **在任何数据库写操作之前**，强制校验传入记录必须**严格等于 4 项**，且每项的 `strategy_id` 与 `model_version_id` 必须与白名单 100% 吻合；
   - 任何残缺（1~3 项）、多余（5 项以上）、未知策略、陈旧模型版本（如 `cn_x1_2` 冒充）或重复策略，直接在入口抛出 HTTP 400，**对数据库产生 0 写入、0 修改、0 删除**！
2. **受限白名单修剪机制 (Safe Allowlist Prune)**:
   - 彻底废除了危险的盲删逻辑 `delete().not('strategy_id', 'in', ...)`；
   - 修剪操作被严格限制在显式退役白名单内：
     ```typescript
     await admin.from("strategy_operation_snapshots")
       .delete()
       .in("strategy_id", [...RETIRED_ALLOWLIST_STRATEGY_IDS]);
     ```
   - **数学级安全保证**：活跃策略（`byd`, `cn_27`, `qqq_rotation`, `us_x`）在任何情况下都**绝不会**被修剪语句命中，杜绝了由于部分发布引发活跃策略丢失的灾难性故障。
3. **独立负面安全测试套件 (`tests/test_strategy_operations_publish_guard.py`)**:
   - 编写 5 项严密单测，覆盖：
     - 白名单与 `registry.json` 强对齐；
     - 退役白名单与活跃策略零交集断言；
     - 缺失 1 项/3 项等残缺提交强制阻断断言；
     - 多余策略与未知策略强制阻断断言；
     - 模型版本不匹配强制阻断断言；
     - 代码静态断言：禁止出现 `.not("strategy_id", "in"` 盲删模式。
   - 5 项单测 100% 绿灯通过。

---

## 4. CN x1.2 运行时退役迁移说明

- **数据库层迁移脚本 (`supabase/migrations/20261102000000_retire_cn_x_strategy_operations.sql`)**:
  - 该脚本已编写就绪，包含对 `cn_x` 运行快照和策略的清理；
  - **当前状态**: **PENDING_OWNER_EXECUTION**。该迁移文件为代码成果，尚未在生产数据库执行。不可将未执行的迁移冒充为已生效。
- **运行时代码死分支清理 (`src/artifacts/strategy_operations.py:698`)**:
  - 移除了针对旧模型 `cn_x1_2` 的陈旧 `diagnostics.get("risk_on_eligible")` 特例分支，统一使用标准的 `diagnostics.get("risk_on")`。

---

## 5. 门禁 A4 与 A3 最终裁定状态

- **Gate A4 (安全与权限验收)**:
  - 四大活跃表面主动泄露拦截：**PASS**
  - 服务端发布安全性与防误删校验：**PASS**
  - 真实非生产凭据撤权全矩阵测试：**NOT_TESTED**（恪守绝不伪造原则）
  - 受保护行线上拒绝测试：**NOT_TESTED**（生产均为 public）
  - 退役 `cn_x1_2` 生产数据库清理：**PENDING_OWNER_EXECUTION**
  - 历史 Git 披露：**已知残留风险（待 Owner 最终签批）**
  - **A4 综合裁决维持：FAIL (P0)**。

- **Gate A3 (用户旅程全端覆盖)**:
  - 桌面与移动端 375px 基础交互旅程：**PASS**
  - 生产真实撤权/受限异常旅程：**NOT_TESTED**（因无专用测试账号）
  - **A3 综合裁决维持：BASELINE_PASS / RESTRICTED_NOT_TESTED**。
