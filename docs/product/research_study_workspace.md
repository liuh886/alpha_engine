# Alpha Research · 研究工作流

**产品定位**：单人使用的投资研究基础设施（Investment Research Infrastructure）。研究问题、可用数据、实验与证据应当可发现、可运行、可比较、可否决，而不需要每一个想法都重写采集和回测脚本。

## 研究者现在能够完成的任务

首次使用时执行：

```bash
uv run alpha research study list
uv run alpha research study init --output artifacts/my-study.json
uv run alpha research study run --spec artifacts/my-study.json
```

第一条返回**一个真实可执行**的研究家族 `us_tech_vol_reversal_v1`，同时从现有 `configs/research_experiments/*.yaml` 列出历史研究及其真实 `status`、目的和原始 spec 路径。历史已结项、未支持或过时的研究**不会**被错误地标注为可直接运行。

第二条创建可编辑的 `WalkForwardConfig` JSON。用户可以改变研究假设的文字、候选股票、基准、时间折叠、参数选择和摩擦成本。但**因子定义**仍是现有的「20 日波动率与 5 日反转」，不会因为调整一个 JSON 字段而自动产生新算法。

第三条使用已实现的 `run_walkforward_study()` 与受治理数据切片执行，并在本地保留结果：

```text
artifacts/research_studies/<study_id>/<study_hash>.json
```

重放相同经济与证据输入时保留第一次结果，不覆盖；报告日期变化本身不制造一份新研究。不同结论却碰巧指定同一输出地址，直接阻断覆盖。被阻断的实验仍保留 `blocked_reasons`、输入和哈希，命令退出码为 10。

两次运行生成收据之后，可以比较：

```bash
uv run alpha research study compare artifacts/research_studies/<id>/<left_hash>.json artifacts/research_studies/<id>/<right_hash>.json
```

比较要求两份结果均为 `ready` 且 `research_only=true`、`trade_ready=false`，匹配模型、交易日窗口、候选股票与基准、价格角色、Fold 数据哈希、执行代码指纹；不相等则如实拒绝。成立时只报告右侧减左侧的净收益、超额收益、Sharpe 与回撤，**不做自动模型晋级或交易建议**。

## 为什么是这个实现

- 单一数据读取权威：`src/data/research_slice.py`，不增添交易数据缓存、第二数据库或自行采集。
- 单一计算权威：`src/research/walkforward/pipeline.py`；本产品入口不重写统计量、回测、参数冻结与净值。
- 单一入口：现有 `src/cli/main.py` 的 `alpha research study`，功能模块独立放在 `src/research/study_workspace.py`。
- 本地收据是**实验产物**而不是新的 canonical market dataset。所有输出禁止包含账户、当前交易目标及信号，并保留 `pit_certified=false` 约束。
- 不重新引入已删掉的 Research Studio 或前端第二导航体系。

## 下一步产品功能，不再以底层引擎版本号排序

| 阶段 | 用户问题 | 最小交付 | 完成度 |
| --- | --- | --- | --- |
| 1. Discover | 我可以研究什么？哪些想法曾被否定？ | 活跃研究入口 + 既有历史研究发现 | 已提交到功能 PR，待 CI |
| 2. Experiment | 如何不用自己写脚本就可改条件、运行、获得证据？ | `init / run / 不可变收据`，已有 WFO 执行器 | 已提交到功能 PR，待 CI |
| 3. Compare | 这个假设的修订真的改善了吗？是否在同一历史证据上？ | 严格对比相同数据下的实验结果，失败可解释 | 已提交到功能 PR，待 CI |
| 4. Expand | 我怎样研究*新的因子*、宏观风险事件、不同市场？ | 接入**现有** spec-driven cross-sectional runner 和 #1272 RDI，统一实验契约；禁止把已结项实验误作新机会 | 尚未实施 |
| 5. Review | 如何在浏览器中审阅结果？ | 只有经过数据授权与隐私审查的研究摘要只读投影；不重新制作浏览器 IDE | 尚未实施 |

首期验证应当由真实研究者从 `list` 到 `compare` 完成一个小的条件性假设比较，并核对两份收据的哈希、阻断、成本与日期资格。**收益率不是平台开发的 DoD**；可信地否决错误假设也属于成功。

**隔离范围**：现有 Direction A 四策略生产、现行 Strategy Console、定时流水线、公共投影及 #1288 安全问题均不改变。研究成功不等于产品 A0–A7 达到 GO。
