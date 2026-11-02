# Direction A v1 官方候选发布清单 (Release Candidate Manifest)

- **候选发布标识**: `rc_direction_a_v1_20261102`
- **生成日期**: 2026-11-02
- **部署 Git SHA**: `4202741d81ba663f551e231e1133e98b061451d4` (`main`)
- **Pages 部署 SHA**: `f97d8b55077d85ea7aa559f2146f4817a3a92543`
- **治理约束**: `research_only=true` / `trade_ready=false`，不可变数据与证据，Fail-closed。

---

## 1. 核心发布组件绑定

### 1.1 四大正式模型身份 (Formal Baseline Models)
四策略模型与其正式 Evidence 切片（截止日 2026-10-30）已完全冻结：

| 策略 ID | 模型版本 ID | 模型家族 | 市场 | Formal Bundle ID | 清单 SHA-256 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`byd`** | `byd_v1_3_recovery_event_low_vol_confirmation_v1` | `byd_allocation` | CN | `5b35c849ca...` | `eb3e676d62...` |
| **`cn_27`** | `cn_27_v1_3` | `cn_27_rotation` | CN | `3212bd7cee...` | `00f3121744...` |
| **`qqq_rotation`** | `qqqi_qqq_tqqq_v4_3` | `qqq_rotation` | US | `12764f1145...` | `78d1783b65...` |
| **`us_x`** | `us_x1_3` | `us_ranker` | US | `f69bac180f...` | `5096420032...` |

### 1.2 生产 Pages 部署验证收据
- **已验证 Commit**: `f97d8b55077d85ea7aa559f2146f4817a3a92543`
- **核验项目**: 36 个正式分节核验通过，4 大活跃模型全部匹配，敏感 `operating_state` 与目标仓位泄露计数为 **0**。
- **验证命令**: `python scripts/verify_pages_release.py --base-url https://liuh886.github.io/alpha_engine/ --expected-commit f97d8b55077d85ea7aa559f2146f4817a3a92543` $\to$ **`status: verified`**。

### 1.3 私有数据与运行账本版本
- **私有归档提交版本**: `a1efd513c06fe95eeb9a291cc6771399ce863025`
- **归档 SHA-256**: `385df76bb8dae516e195899a912f3db2d55411c080b6386528f76b3630b5f9f1` (493,139 字节)
- **校验捕获总数**: 405 个归档快照，58 次正式运行尝试。

---

## 2. A5 有界验收口径与 A6 Owner 批准操作明界

### 2.1 A5 有界回放验收口径 (Bounded Replay Standard)
- **数学精度标准**: 容差严格限制在 $\le 10^{-6}$。
- **CN 27 v1.3**: 本地重放完成，exit code 0，回放净值与正式基准绝对差为 0.00000000，标记为 `exact_replay`。
- **QQQ Rotation v4.3**: 本地由于缺少 2026-10-30 相比本机 2026-10-23 的外部 Yahoo 原始日线切片，系统执行 Fail-closed 拒绝编造数据，如实记录为 `blocked`。
- **口径界定**: A5 确认系统具备严格的有界重放能力与防伪造阻断机制；待 Owner 确认是否接受该有界证据。

### 2.2 A6 生产级操作的 Owner 专属审批边界
根据单操作员运行手册，以下关键生产动作**必须由 Owner 本人执行或明确签批**，自动化 Agent 绝不擅自越权：
1. **Pages 生产自定义域名或重大基线切换**: 必须由 Owner 使用明确的 `--expected-commit` 参数运行 `scripts/verify_pages_release.py` 确认无误后发布。
2. **生产环境物理版本回滚**: 必须由 Owner 审查目标 SHA，核验该 SHA 是否包含隐私保护补丁（#1288），严禁直接将未脱敏历史旧版本回滚上线。
3. **生产数据库权限与结构迁移**: 针对 `supabase/migrations/20261102000000_retire_cn_x_strategy_operations.sql`（清理 `cn_x` 退役运行行），须由 Owner 在生产 Supabase 控制台执行或配置专用 CI 密钥执行迁移。

---

## 3. 全量门禁 A0–A7 状态矩阵

| 门禁 | 判定状态 | 关键依据与说明 |
| :--- | :--- | :--- |
| **A0 身份权威** | **PASS** | 单一统一 ResearchAssistant；四策略与 ADR-0003 唯一权威对齐。 |
| **A1 真实运行** | **BLOCKED** | 12/20 会话被观测，0 独立合格；自然交易日随时间累积，绝不伪造。 |
| **A2 数据可信** | **OPS_PASS** | 四策略运行所需数据源全部对账闭环；US87/CN130 训练宽表隔离阻塞。 |
| **A3 用户旅程** | **BASELINE_PASS** | 8 条基础交互路径在桌面与移动端 375px 全绿；真实撤权会话因无专用测试账号客观记为 NOT_TESTED。 |
| **A4 权限安全** | **CONDITIONAL_FAIL** | 主动四大泄露面完全切断；`cn_x` 迁移方案就绪；历史 Git 披露作为已知残留风险等待 Owner 签批。 |
| **A5 本地研究** | **BOUNDED_PASS** | CN27 精确重放，QQQ 真实记录缺源阻断；有界回放口径等待 Owner 验收。 |
| **A6 发布恢复** | **REHEARSAL_PASS** | 篡改证据 100% 拦截，离线恢复验证通过；生产发布回滚边界已明确。 |
| **A7 终审裁决** | **PENDING_OWNER** | **Agent 综合建议维持：NO-GO**。等待 A1 交易日自然累积与 Owner 终审签批。 |
