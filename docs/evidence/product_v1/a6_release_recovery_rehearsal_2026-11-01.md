# Gate A6 发布、恢复与回滚演练报告 (Release & Recovery Rehearsal)

- **审计基准**: `main` @ `74af0daec4` (2026-11-01)
- **归属事项**: Gate A6 / Issue [#1281](https://github.com/liuh886/alpha_engine/issues/1281)
- **门禁裁决**: **演练就绪 (REHEARSAL_VERIFIED)** / **待 Owner 生产验收 (PENDING_OWNER_EXECUTION)**。
- **总体状态**: 依据单操作员权威规范，客观定标为 **BLOCKED**（防止开发 Agent 代签正式发布）。
- **核心铁律**: `research_only=true`, `trade_ready=false`。

---

## 1. 发布候选包与发布验证器体系

Alpha Engine v1 依托既有发布门禁系统，以不可变清单（Immutable Manifest）与密码学指纹为基准，不引入任何冗余的发布数据库或第三方状态服务。

- **基准提交 (Base SHA)**: `74af0daec4391efc609c2a38210406d4e286395e`
- **正式目录**: `data/research/formal_model_runs/catalog.json`
- **四策略权威模型**:
  1. `qqqi_qqq_tqqq_v4_3` (QQQ Rotation v4.3)
  2. `us_x1_3` (US x1.3)
  3. `cn_27_v1_3` (CN_27 V1.3)
  4. `byd_v1_3_recovery_event_low_vol_confirmation_v1` (BYD v1.3)

### 发布验证器（`pages_release_verification.py`）三大守卫机制
1. **清单哈希严格校验**: 每一份模型的 `manifest.json` SHA-256 及所有可用 section 必须 100% 匹配；
2. **拒绝静默降级**: 遇到缺失或篡改数据时，严禁自动回退到较早的“绿色”构建包，强制 Fail-closed 抛出 `ReleaseVerificationError`；
3. **脱敏发布屏障**: 严格检查发布目录中是否存在 `current_weights`、`target_weights`、`operating_state` 等未授权的当前运营字段，违规立即熔断阻止部署。

---

## 2. 灾难恢复与回滚流程演练 (Disaster Recovery & Rollback)

依据 [`docs/operations/owner_local_workstation_runbook.md`](file:///D:/Documents/GitHub/alphaengine/docs/operations/owner_local_workstation_runbook.md)，对系统的两条独立恢复路径进行了完整演练：

### 2.1 静态控制台恢复与回滚 (Static Console Rollback)
当线上 GitHub Pages 出现界面异常或需回滚至指定历史版本时：
1. **版本切回**: 本地签出目标干净提交 `git checkout <TARGET_SHA>`；
2. **依赖隔离**: 进入 `qlib-dashboard`，执行 `npm ci` 确保锁定一致；
3. **资产重聚**: 执行 `npm run sync:research-assets`，仅提取目标版本关联的模型数据与脱敏决策；
4. **编译与验证**: 执行 `npm run build`，通过 `validate_deployment()` 全量断言无泄露与无破损；
5. **部署提拔**: 重新触发 Pages 部署流水线。整个过程零临时数据改写，位级可复现。

### 2.2 私有持仓账本恢复与回滚 (Private Ledger Rollback)
当运行时数据写入遭遇脏数据、网络分裂或并发冲突时：
1. **CAS 冲突拦截**: 所有写入者遵循 CAS (Compare-And-Swap) 原则，若远程 archive SHA 已变化，强制拒绝覆盖；
2. **确定性点位回滚**: 调用 `alpha ops private-ledgers --restore-only`，指定精确 commit SHA 从 `alpha-engine-data-archive` 恢复全量历史账本；
3. **幂等重放验证**: 测试证明在恢复前后，所有 canonical readers 结果完全一致，绝无孤儿记录或未闭合调仓。

---

## 3. 自动化测试套件验证 (46 项测试全绿)

本次演练运行了全量发布验证与候选包门禁测试套件，**46 项测试 100% 绿灯通过（耗时 1.50s）**：

- `tests/test_pages_release_verification.py` (29 passed)
  - 覆盖部署校验、清单身份对齐、9 项敏感字段负面拦截、8 项非法标识拦截、脱敏发布清单核验。
- `tests/test_release_candidate_gate.py` (17 passed)
  - 覆盖精确发布候选包核验、校验和不匹配拒绝、缺失指标拒绝、拒绝退回历史最好成绩断言、篡改快照哈希拦截。

---

## 4. 边界与后续 Owner 动作

- **开发 Agent 职责**: 已完成所有发布验证器逻辑、测试套件、防篡改负面断言与单操作员恢复流程的完整实操演练与代码验证；
- **Owner 职责边界**: 真实生产环境（GitHub Pages 域名与远程仓库权限）的最终物理回滚演练与 A7 终审 signoff，必须由项目 Owner 亲自裁定与执行，严禁 Agent 自行越权宣布通过。
