# Gate A4 / A3 权限缺口治理与事实裁定 (Permission Policy Resolution)

- **基准日期**: 2026-11-02
- **归属工单**: Gate A4 / Gate A3 / Issue [#1279](https://github.com/liuh886/alpha_engine/pull/1279) / Issue [#1288](https://github.com/liuh886/alpha_engine/issues/1288)
- **执行原则**: 恪守 `research_only=true` / `trade_ready=false`，严禁为验收在生产环境中伪造测试账号或临时修改生产权限策略，维持客观事实与 Fail-closed 铁律。

---

## 1. 四策略确切权限策略矩阵

经对 `configs/strategies/registry.json`（静态策略注册表）与 `supabase/migrations/`（Postgres RLS / PostgREST 访问控制策略）的端到端对账，四策略的确切权限定义如下：

| 策略 ID | 策略展示名 | 历史证据权限 (`registry.json`) | 运行时实时快照权限 (`product_access_policies`) | 匿名访问行为 | 认证用户 (`authenticated`) 行为 | Pro / Owner 行为 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`byd`** | BYD v1.3 | `public` | `public` | 允许只读查看历史与运行快照 | 允许只读查看 | 允许只读查看 |
| **`cn_27`** | CN_27 V1.3 | `public` | `public` | 允许只读查看历史与运行快照 | 允许只读查看 | 允许只读查看 |
| **`us_x`** | US x1.3 | `public` | `public` | 允许只读查看历史与运行快照 | 允许只读查看 | 允许只读查看 |
| **`qqq_rotation`** | QQQ Rotation v4.3 | `public` | `pro` | 允许查看历史脱敏证据；实时运行快照标记为 `protected` | 实时运行快照标记为 `protected` | 允许读取实时运行快照 |

### 核心权限架构设计解析
1. **静态证据面 (Historical Evidence)**：
   - 四大策略在 GitHub Pages 静态分发层均为 `historical_evidence_access: "public"`。
   - 经过 `sync-formal-model-runs.mjs` 脱敏后，完全剥离了敏感 `operating_state` 与目标权重，作为公开研究透明度资产提供。
2. **运行时快照面 (Current Operations Snapshots)**：
   - 存储于 Supabase 私有数据库 `public.strategy_operation_snapshots` 表中，由 RLS（行级安全策略）严格守护。
   - `byd`, `cn_27`, `us_x` 为 `public` 级，匿名用户可通过公共网关读取只读运行状态。
   - `qqq_rotation` 在 `20260812022634_alpha_engine_strategy_access_policies.sql` 中明确标定为 `required_tier = 'pro'`，非 Pro 角色读取时由 RLS 策略或前端 `useStrategyOperations` 拦截并标定为 `protected`。
3. **严格 Fail-closed 默认安全基线**:
   - 若任何策略未在 `product_access_policies` 中显式声明，`resolveRequiredTier` 会确定性回退至 `'owner'` 级别；
   - 数据库 RLS 函数 `has_product_tier_access` 对缺失策略行直接拒绝访问，绝不静默放行。

---

## 2. 真实授权、拒绝与撤权行为核验 (合规边界与禁止伪造声明)

根据指令要求：“先确定四策略当前状态究竟采用何种权限策略，再验证真实授权、拒绝和撤权行为，不要为了验收虚构测试账户或改变生产权限。”

### 核验结果与客观记录：
1. **真实公开/授权访问**:
   - 在生产 Pages 部署 (`f97d8b5507`) 与本地验证器中，匿名用户能够成功读取 `byd`, `cn_27`, `us_x` 的公开证据，且无任何数据泄露（36 formal sections verified，0 violations）。
2. **非授权与越界访问拒绝**:
   - 对未注册策略（如请求非法策略 ID 或未授权受保护资源）的匿名与低权限读取，系统严格执行 Fail-Closed：返回 404 或空数据集，不会暴露敏感数据。
   - 单元测试覆盖：`tests/test_strategy_access_policy_coverage.py`（2 项通过）、`qlib-dashboard/src/hooks/useStrategyOperations.test.tsx`（覆盖 403 拒绝与 protected 状态）。
3. **关于生产 Token 过期/撤权测试的真实边界**:
   - **事实说明**：由于生产环境中**未配置独立的非生产测试专用凭据**（如专用的失效/撤权 JWT 测试账号），且我们**严禁在生产数据库中临时创建虚假测试用户或篡改现有生产策略**；
   - **合规标定**：针对线上生产环境的“过期 Token 访问拒绝”与“中途撤权即时失效”会话，依据 Fail-closed 铁律，客观记录为 **NOT_TESTED_IN_PROD (Due to zero fake test account policy)**，坚决不通过伪造测试来虚标 PASS。

---

## 3. CN x1.2 运行时退役彻底收口

为彻底消除已批准退役的 `cn_x1_2` 运行时快照残留风险，本次攻坚完成了三层物理级与逻辑级清理：

1. **数据库层迁移脚本 (`supabase/migrations/20261102000000_retire_cn_x_strategy_operations.sql`)**:
   - 编写确定性 SQL：
     ```sql
     delete from public.strategy_operation_snapshots where strategy_id = 'cn_x';
     delete from public.product_access_policies where product_code = 'alpha_engine' and resource_type = 'strategy' and resource_id = 'cn_x';
     ```
   - 确保生产数据库迁移后，`cn_x` 不再占用运行行，也不会作为孤儿快照暴露。
2. **发布 Edge Function 自动化修剪 (`supabase/functions/alpha-engine-publish-strategy-operations/index.ts`)**:
   - 在 upsert 活跃策略快照后，追加自动删除机制：
     ```typescript
     const { error: pruneError } = await admin
       .from("strategy_operation_snapshots")
       .delete()
       .not("strategy_id", "in", `(${[...strategyIds].join(",")})`);
     if (pruneError) throw pruneError;
     ```
   - 确保未来任何策略退役或更替时，非活跃策略快照会被自动修剪，不再残留。
3. **运行时代码死分支清理 (`src/artifacts/strategy_operations.py:698`)**:
   - 移除了针对旧模型 `cn_x1_2` 的陈旧 `diagnostics.get("risk_on_eligible")` 特例分支，统一使用标准的 `diagnostics.get("risk_on")`。
   - 经 `uv run pytest tests/test_strategy_operations.py tests/test_strategy_operations_runtime.py tests/test_public_source_boundary.py` 验证，29 项测试全绿通过。

---

## 4. 门禁 A4 与 A3 最终裁定状态

- **Gate A4 (安全与权限验收)**:
  - 四大活跃表面主动泄露拦截：**PASS**
  - 四策略当前权限定义与 RLS 保护：**PASS**
  - 退役 `cn_x1_2` 运行行清理方案：**PASS**
  - 真实非生产凭据撤权全矩阵测试：**NOT_TESTED**（恪守绝不伪造原则）
  - 历史 Git 披露：**已知残留风险（待 Owner 最终签批）**
  - **A4 综合裁决维持：CONDITIONAL_FAIL / PENDING_OWNER_RISK_ACCEPTANCE**。

- **Gate A3 (用户旅程全端覆盖)**:
  - 桌面与移动端 375px 交互旅程：**PASS**
  - 异常与受限保护旅程渲染：**PASS**
  - 生产真实撤权旅程：**NOT_TESTED**（同上，恪守无假测试账号原则）
  - **A3 综合裁决维持：BASELINE_PASS / RESTRICTED_NOT_TESTED**。
