# AlphaEngine 项目交接文档

**交接日期：2026-07-13**  
**仓库：`liuh886/alpha_engine`**  
**交接基线：`main@224041f2d8271bb34f122e70d9440edc676ac3c4`**

## 1. 当前总状态

AlphaEngine 已完成从“多套研究脚本并行存在”向统一、可复现、fail-closed 的固定 10D 研究范式收敛。当前主链为：

```text
ResearchParadigmSpec
  -> market-specific Qlib provider
  -> spec-bound execution
  -> real-market acceptance
  -> single-factor diagnostics
  -> execution identity
  -> PromotionDecision
  -> read-only consumers
```

当前没有任何因子或模型被批准晋级：

```text
diagnostic_only=true
promotion_eligible=false
promotion_evaluated=false
trade_ready=false
```

## 2. 已完成工作

### 2.1 架构收敛

已完成并关闭 Stage C-F（Issues #95-#98）：

- non-overlapping backtest 统一到 `PortfolioIntent`；
- PromotionDecision 只能在 execution identity 通过后生成；
- CN/US adapter 只生产 evidence，不再拥有生命周期决策权；
- 抽取 market-neutral Qlib execution common core；
- spec-bound 执行链脱离 notebook `ResearchSessionConfig`；
- 多个旧 CN/US specialized runner 已降级为 canonical wrapper；
- universe robustness 与 stable blend 保留为 diagnostic-only；
- ranker 缺失值不再填 0 或中性标签。

### 2.2 真实数据入口与验收

已完成：

- 版本化 CN/US 研究 universe，与 operational watchlist 分离；
- CN 代码前导零与 provider identity 规范化；
- CN、US、HK market-specific Qlib provider；
- 独立市场 calendar，已用真实 pyqlib 证明 `Ref($close,-10)` 按本市场第 10 个 session 计算；
- configured/effective universe 与 partial snapshot truthfulness；
- provider-attempt provenance；
- CSI 300 使用 AkShare `sh000300` 全历史指数接口；
- `cn:000300` 使用 AkShare-first symbol policy；
- OHLC order 校验容忍严格受控的机器精度误差，但仍拒绝实际错误；
- OOS 窗口末尾 10 个 session 被剔除，避免 T+10 标签跨窗。

### 2.3 Issue #124：真实市场验收与因子诊断

Issue #124 已完成并关闭。最终证据已通过 PR #146 固化到：

```text
docs/evidence/issue-124/
```

主要文件：

```text
docs/evidence/issue-124/README.md
docs/evidence/issue-124/evidence_index.json
docs/evidence/issue-124/cn/real_market_acceptance.json
docs/evidence/issue-124/cn/factor_diagnostics.json
docs/evidence/issue-124/cn/real_market_research_manifest.json
docs/evidence/issue-124/us/real_market_acceptance.json
docs/evidence/issue-124/us/factor_diagnostics.json
docs/evidence/issue-124/us/real_market_research_manifest.json
```

最终结果：

| 市场 | 验收 | 完整覆盖 | CSV 完整性 | 因子 ID | 唯一表达式 | 采样日期 |
|---|---:|---:|---:|---:|---:|---:|
| CN | 10 pass / 1 warn / 0 fail | 164 / 223（最低 50） | 165 / 0 invalid / 0 missing | 47 | 23 | 46 |
| US | 10 pass / 1 warn / 0 fail | 120 / 133（最低 30） | 121 / 0 invalid / 0 missing | 24 | 9 | 48 |

最终 SHA-256：

```text
CN acceptance:
52e008b381c389e4a01c2f82124fcc33f1c683d74c64583c71c1778c4597d623

CN diagnostics:
60d2b0d10cd90bbed68aa362416c2cd03eb553f3cd6e26039628ff81706f6b71

CN manifest:
352b09587a64ddf067e813218d93043834c63464ef5b008e0a91dc4e9978f78b

US acceptance:
4d427c9aa2f834b154792add30ce7e1bbbe4bb6d5af5afa24466dbb62fc01c75

US diagnostics:
fc52db50a15a55006a190623d434db8298d5d145e4e5d6245ab6232643c9b776

US manifest:
c9baad0ce4042b010df57bc5e6b8e6f87d835944ca147ff13f0c0e3e64b617d5
```

### 2.4 Canonical factor identity

Issue #147 已由 PR #149 完成并关闭：

- CN：47 factor IDs -> 23 canonical expressions；
- US：24 factor IDs -> 9 canonical expressions；
- leaderboard 与独立统计证据以 canonical expression 为单位；
- ID、group、family、baseline 继续作为 alias/provenance 保留；
- alias metrics 不一致时 fail closed；
- diagnostics schema 升级为 1.2。

## 3. 当前唯一未完成任务

### Issue #148 / Draft PR #150

**Issue：** Define policy for incomplete final OOS windows  
**PR：** `#150 fix(research): make incomplete OOS window policy explicit`  
**当前 head：** `ad08b78309a8ad60944f07952c95c898b9c07149`

目标是将最终不完整半年度窗口的处理方式变成显式、版本化的研究合同：

```yaml
partial_window_policy: complete_windows_only
```

或在明确声明最小 eligible session 数时允许：

```yaml
partial_window_policy: allow_horizon_contained_partial_final_window
min_partial_window_eligible_sessions: <positive integer>
```

硬约束：

- `min_windows` 只统计完整半年度窗口；
- partial window 永远不能帮助满足 `min_windows`；
- partial window 的 T+10 label 必须完全位于 `test_end` 以内；
- CN/US 当前生产 spec 必须继续使用 `complete_windows_only`；
- 2026H1 应被明确记录为“partial and excluded by policy”，而不是静默消失。

## 4. PR #150 当前不可合并的原因

GitHub 显示该 PR mergeable，但从工程成熟度看仍不可合并：

1. `Alpha Engine CI` 已通过；
2. `Patch incomplete OOS window policy` workflow 失败；
3. 当前 diff 仍包含一次性迁移设施：

```text
.github/workflows/patch-incomplete-oos-window-policy.yml
scripts/_patch_incomplete_oos_window_policy.py
scripts/_harden_oos_adapter_sampling.py
scripts/_harden_oos_policy_evidence.py
```

4. 当前永久代码仅出现：

```text
src/research/window_policy.py
tests/test_window_policy.py
```

5. 预期的生产集成尚未完整出现在 final diff 中，包括：

```text
src/research/paradigm.py
src/research/market_data_alignment.py
src/research/spec_bound_factor_diagnostics.py
src/research/spec_bound_execution.py
src/research/cn_qlib_execution_adapter.py
src/research/us_qlib_execution_adapter.py
configs/research_paradigms/cn_10d_csi300_baseline.yaml
configs/research_paradigms/us_10d_qqq_baseline.yaml
tests/fixtures/cn_qlib_ci/paradigm.yaml
tests/test_research_paradigm.py
tests/test_spec_bound_factor_diagnostics.py
```

因此不得仅因为主 CI 为绿色就合并 #150。

## 5. PR #150 接手步骤

### Step 1：从最新 main 同步

```bash
git checkout main
git pull --ff-only
git checkout fix/incomplete-oos-window-policy
git rebase main
```

### Step 2：不要继续依赖脆弱文本 patch workflow

推荐直接将最终修改落入生产文件。一次性 patch/hardening 脚本只可用于参考，不应进入最终 PR。

需要完成的集成：

- `ResearchParadigmSpec` 校验 policy enum 与 minimum session 组合；
- paradigm schema 1.0 -> 1.1；
- execution contract schema 1.0 -> 1.1；
- factor diagnostics schema 1.2 -> 1.3；
- `market_data_alignment` 仅将完整窗口计入 readiness minimum；
- CN/US adapters 使用统一 session-aware planner；
- diagnostics 使用同一 planner；
- walk-forward evidence 输出 natural/effective end、complete/partial、include/exclude reason、eligible/excluded/sampled sessions；
- 两份生产 spec 显式声明 `complete_windows_only`；
- fixture spec 同步更新。

### Step 3：最终 diff 清理

合并前必须删除：

```text
.github/workflows/patch-incomplete-oos-window-policy.yml
scripts/_patch_incomplete_oos_window_policy.py
scripts/_harden_oos_adapter_sampling.py
scripts/_harden_oos_policy_evidence.py
```

最终 diff 只能保留生产代码、canonical specs 与永久测试。

### Step 4：必测场景

至少验证：

1. `complete_windows_only`：2026H1 明确记录为 partial/excluded；
2. allow policy + 足够 eligible sessions：partial final window 可作为额外证据；
3. allow policy + session 数不足：fail closed；
4. partial window 不计入 `min_windows`；
5. selected signal 的第 10 个未来 session 不超过 effective test end；
6. CN/US adapter 与 factor diagnostics 使用完全相同的 selected windows；
7. 修改 policy 或 minimum session 会改变 execution contract hash；
8. 不改变 factor expressions、universe、benchmark、日期、10D cadence、Top/Bottom N 或 promotion gates。

### Step 5：最终 CI

```bash
uv run ruff check src api_server.py
uv run mypy src/release src/models/metric_contract.py
uv run pytest <完整 Fast PR 测试集合> -q --strict-markers --tb=short --disable-warnings --maxfail=1
uv run pytest tests/test_cn_qlib_ci_integration.py -q --strict-markers --tb=short --disable-warnings --maxfail=1
```

同时要求：

- frontend TypeScript、lint、unit tests 通过；
- GitGuardian 通过；
- PR final head 不再运行或包含一次性 patch workflow。

## 6. #150 合并后的证据处理

### 历史证据

`docs/evidence/issue-124/` 是当时合同下的真实、不可变历史证据，不应删除或覆盖。

### 新合同证据

#150 会改变 schema 与 execution contract hash。虽然生产 policy 仍为 `complete_windows_only`，结果窗口应仍是：

```text
2024H1
2024H2
2025H1
2025H2
```

但在继续做因子库取舍前，应基于 #150 合并后的 main 重新运行一次 CN/US pipeline，生成当前合同版本的 acceptance、diagnostics 和 manifest。新 evidence 应新建目录或版本，不覆盖 Issue #124 的归档文件。

Canonical 本地命令：

```bash
uv sync --frozen --extra dev
uv run python scripts/update_data.py --full --start 2021-01-01 --market all
uv run python scripts/build_market_providers.py --root . --markets cn us
uv run python scripts/run_real_market_research.py --root . --spec configs/research_paradigms/cn_10d_csi300_baseline.yaml
uv run python scripts/run_real_market_research.py --root . --spec configs/research_paradigms/us_10d_qqq_baseline.yaml
```

只有在 GitHub Actions 因公共行情源限速、缓存缺失或 runner 时长限制无法完成时，才需要本地 agent 执行该步骤。

## 7. 后续因子研究建议

完成 #150 与新合同证据后，再开启独立 factor-review issue。不得在同一个 PR 中同时修改 universe、日期、cadence、factor expression 和 gate。

当前证据的保守结论：

- CN 最强 canonical expression 的 oriented ICIR 约 0.215，窗口方向一致率仅 50%；
- US 最强 canonical expression 的 oriented ICIR 约 0.287，风险调整领先表达式仅 50% 窗口同向；
- CN 若干 volatility 表达式存在 oriented IC 与 Top-Bottom spread 方向不一致；
- US 20D momentum、20D risk-controlled momentum 和 volatility 可保留为研究候选，但不具备 promotion 强度。

下一阶段建议按 canonical expression 分三类：

1. **retain for research**：IC、spread 与方向一致，但强度不足；
2. **isolate / investigate**：IC 与 spread 不一致，或仅少数窗口有效；
3. **remove from candidate grid**：低覆盖、近零信号或长期方向不稳定。

任何 keep/invert/remove 决策必须引用新 evidence hash，并继续保持：

```text
promotion_eligible=false
trade_ready=false
```

直到后续 spec-bound model run、execution identity、完整 walk-forward evidence 和 canonical PromotionDecision 全部通过。

## 8. 接手完成定义

本轮交接视为完成，当且仅当：

- [x] Issue #124 最终真实证据已固化并关闭；
- [x] Issue #147 canonical factor identity 已完成；
- [ ] PR #150 生产集成完整；
- [ ] PR #150 一次性脚本/workflow 全部删除；
- [ ] PR #150 final CI 全绿并合并；
- [ ] Issue #148 关闭；
- [ ] 基于新合同重新生成 CN/US 当前证据；
- [ ] 新建独立 factor-review issue，且不混改研究合同。
