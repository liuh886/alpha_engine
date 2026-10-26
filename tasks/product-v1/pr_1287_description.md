# PR #1287 : docs(evidence): audit four-strategy live journeys and privacy gaps (#1279)

A4 FAIL: additional anonymous section scan confirmed CN_27 public lineage includes current operating weights/targets/factor evidence. Exact path/hash without allocation values retained; separate observed defect #1288 requires owner-reviewed publication/integrity design before implementation. Existing snapshot-only static-shell check is insufficient.

Evidence audit for #1279 (W1b–W2), not closure of A3/A4. Published main 58a56c14c / deploy 40170378446 / formal cutoff 2026-10-23. All four accepted strategies passed Overview → Detail → linked Instrument → Status on desktop/mobile (8 real journeys). Existing 2 live and 60 fixture browser checks, 216 unit tests/build, 36 formal-section/static-public-shell verification passed. Matrix includes actual URLs, identities, outcomes, screenshot/trace hashes and two reviewed historical screenshots.

Live RLS policies currently declare all current strategy resources public; anonymous query returns those authorized rows (also retained cn_x), invalid token returns 401. No protected data, keys or tokens are committed. This cannot certify Pro denial or real member/Pro/owner expiry/revocation; owner must review intended policy. Actual changed/not-due/blocked/expired samples per strategy remain NOT_TESTED. Fixtures never count as real account/session evidence. No policy writes, UI redesign, schema/strategy/runtime changes or automatic release.

Rollback: revert derived audit artifacts only. Raw traces remain local (hashed); shared durable coverage is not claimed. Owner/architecture review required before merge.

---

<!-- infrastructure-alignment-2026-10-26 -->
## 2026-10-26 战略对齐｜本地 Agent 执行指引

**归属：Track A / P0 权限安全验证 + P1 四策略用户路径；与长期研究基础设施共用“研究数据公开/当前运行私有”的边界。**

**本地 Agent 后续任务：**
1. 完成四策略 Desktop/Mobile 用户旅程的真实状态矩阵：changed、unchanged/not-due、provider delayed/blocked、登录/权限拒绝、expired/revoked；记录可证明的实际截图/请求/运行日期/模型身份，而不是把 fixture 结果标成已观察现场。
2. 在 #1291 owner 批准的发布架构下，扩大负面审计到 **Git 树、Pages 每个正式 published section、CI artifacts、runtime current-state readers**；公开正式历史可读，但 current weights/targets/drivers/ledger 敏感字段不能通过匿名静态资源泄露。
3. 真实核实 anonymous/member/Pro/owner 的既有 intended policy（需 owner 明确层级），测试过期 token、撤权、身份切换、缓存/previous-read 清空；当前全部公开的 RLS 配置属于已观察行为，不得自行推测哪一等级应拒绝。
4. 缺陷由 #1288/#1291 的独立实现 PR 解决；本 PR 负责证据与复核，不要在审计分支直接变更 RLS、sealed bundles 或恢复退休浏览器入口。

**预期成果：** 每策略 × 场景 × 终端 × 权限的可审计 UAT 矩阵，以及发布安全修复前/后的匿名负面证据与独立复核报告。

**验收/边界：** A3 未有真实异常状态覆盖前继续 BLOCKED；A4 未通过真实 Git/Pages/RLS 负面验证前继续 FAIL。不得上传令牌、真实仓位数值或受保护信号到公开报告；不把 #1296 新数据查询服务作为现有权限缺陷的替代修复。
