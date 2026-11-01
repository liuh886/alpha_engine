# Gate A4 权限、披露与访问控制审计报告 (Security & Access Audit)

- **审计基准**: `main` @ `76db41401c` (2026-11-01)
- **归属事项**: Gate A4 / Issue [#1279](https://github.com/liuh886/alpha_engine/pull/1279) / Issue [#1288](https://github.com/liuh886/alpha_engine/issues/1288)
- **门禁裁决**: **维持 FAIL (P0)**。
- **裁决理由**: 活动公开泄露已在四大表面（公开 Git、Pages、Actions 制品、写入流水线）成功止血并形成独立负面证明；但依据 Fail-closed 铁律，因缺少非生产专用测试账号，受保护行的真实会话拒绝/授权/撤权验证保持 **NOT_TESTED**，历史 Git 存在已知暴露，退役 `cn_x1_2` 运行行待清理。在真实权限全矩阵未获独立验收前，**门禁 A4 绝不虚标 PASS**。

---

## 1. 五大安全暴露面全景审计矩阵

根据 [`docs/architecture/current_operations_security_audit_1288.md`](file:///D:/Documents/GitHub/alphaengine/docs/architecture/current_operations_security_audit_1288.md) 的标准，对系统全部五个潜在数据暴露面进行了逐一核查与对账：

| 暴露面 | 审计对象 | 现状与治理成果 | 状态裁决 | 自动化测试用例 |
| :--- | :--- | :--- | :--- | :--- |
| **1. 公开 Git** | 仓库当前追踪文件 (`main`) | 四策略活跃运行账本已完全从 Git 追踪中剔除；本地水合路径已由 `.gitignore` 忽略；对活跃最新路径的 16 次匿名请求均确定性返回 **404**。 | **已止血并脱敏** | `test_active_runtime_ledgers_are_not_git_tracked_and_fresh_hydration_is_ignored` |
| **2. 历史 Git** | 切割点之前的提交历史 | 历史提交中包含已披露的仓位/权重数据。依据 ADR-0004，历史不可逆向篡改或强制重写，作为**已封存的残留风险**记录，全面停止未来写入。 | **记录为残留风险** | 架构文档 §1 固化 |
| **3. Pages 部署** | 静态构建产物 (`qlib-dashboard/dist`) | `sync-formal-model-runs.mjs` 自动剥离 `operating_state`、`current_weights` 与 `target_weights`；已部署的静态 Shell 呈现 0 仓位、0 因子证据。 | **构建与发布级受控** | `test_public_formal_runs_have_zero_operational_leakage`<br>`test_cn_27_historical_projection_identity_contract`<br>`test_all_public_formal_assets_pass_release_verifier` |
| **4. Actions 制品** | CI 工作流产出的 Artifacts | 每日策略警报工作流已收口为仅上传元数据收据（`result.json`）；正式回测刷新流水线（如 Run 41083709573）仅上传归档绑定，敏感字段计数严格为 0。 | **脱敏与限域遮蔽** | `test_every_producer_restores_before_due_and_persists_without_public_mirror` |
| **5. 写入流水线** | 自动化定时工作流 | 四策略生产者（QQQ, BYD, Ranker, CN27）与 Formal 事务彻底移除了 `git commit/push` 公开操作，100% 切换至带 CAS 冲突检测的私有存储库（`alpha-engine-data-archive`）SSH 传输。 | **私有化物理隔离** | `test_formal_transaction_pins_one_private_revision_across_all_consumers`<br>`test_operations_resolves_private_content_before_cache_lookup`<br>`test_outbox_private_probe_cannot_invoke_notifications_or_dispatch` |

---

## 2. 自动化安全测试验证 (82 项测试全绿)

本次审计执行了涵盖安全边界、信号发布、私有账本、流水线事务与策略运维的全部 82 项单测，**全部 100% 绿灯通过**：

- `tests/test_public_source_boundary.py` (7 passed)
- `tests/test_signal_publication_boundary.py` (8 passed)
- `tests/test_private_signal_ledger.py` (10 passed)
- `tests/test_strategy_signal_checkpoint.py` (21 passed)
- `tests/test_private_ledger_workflows.py` (7 passed)
- `tests/test_strategy_operations.py` (19 passed)
- `tests/test_strategy_operations_release.py` (7 passed)
- `tests/test_strategy_operations_runtime.py` (3 passed)

---

## 3. 核心阻塞原因与为什么维持 FAIL

虽然四大主要泄露面的主动暴露已完全切断，但依据系统安全与合规最高准则，Gate A4 依然被标记为 **FAIL**：

1. **真实会话权限矩阵未执行 (NOT_TESTED)**:
   - 当前生产环境中策略的 `required_tier` 均为 `public`；
   - 系统中不存在非 public 的受保护策略行来验证“未授权访问确定性返回 403/404”；
   - 操作员确认目前没有独立的专用测试账号（Pro / Free / Expired），因此**真实授权/无权/过期/撤权会话验收**无法在生产环境真实模拟。在没有专用测试会话前，绝不虚报 PASS。
2. **退役模型当前运行行残留**:
   - 历史退役的 `cn_x1_2` 运行时快照依然挂载在 `cn_x` 策略下可读，尚未通过正式的治理流程从运行时彻底注销。
3. **历史披露的法律与安全事实**:
   - Git 历史记录中的敏感字段依然可被追溯，属于不可磨灭的既成事实，需由 Owner 正式知悉并签署接受该残留风险。

---

## 4. 下一步行动建议

1. **Owner 治理动作**:
   - 签署确认历史 Git 提交披露为已知残留风险；
   - 批准在运行时正式注销 `cn_x1_2` 旧模型行；
   - 如需在 A7 之前闭环真实权限矩阵，需为系统配置一组受隔离的测试用凭据。
2. **转向下一优先级**:
   - 推进 **Gate A6 发布与恢复演练 (#1281)**，验证指定 SHA 的隔离恢复、错误证据拦截与回滚机制。
