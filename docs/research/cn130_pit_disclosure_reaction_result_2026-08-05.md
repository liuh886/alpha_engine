# CN130 PIT财报披露反应条件化实验结果

Issue: #550  
Draft PR: #551  
Decision: `disclosure_reaction_architecture_not_supported`  
Boundary: `research_only=true`, `trade_ready=false`

## 结论

本轮第一次在CN130新信息路径中找到通过预注册稳定性门槛的组件：财报披露后首个可交易日的、相对沪深300的异常开盘缺口（`abnormal_gap_1`）。

但是，把该组件直接用于R0 Top3重排、负反应换股或负反应持有现金，均未通过组合架构门。因此2024–2025冻结验证保持关闭，不创建CN x1.1候选。

## 组件证据

`abnormal_gap_1`在R0所选行业Top3中的最近事件覆盖率为24.50%，校准结果为：

- 平均Rank IC：0.1419；
- 平均增量Rank IC：0.1172；
- 三个校准半年全部为正；
- 最差半年Rank IC：0.0136；
- Top-minus-Bottom spread：2.59%；
- 最大行业绝对spread占比：28.5%。

分窗口Rank IC：

- 2022H2：0.2460；
- 2023H1：0.0136；
- 2023H2：0.1661。

单日和三日异常收盘收益、单日和三日成交额放大均未通过完整门槛。

## 架构证据

20bps下，校准期R0基线E0相对超额为-30.42%。事件Top3重排E1提高到-2.48%，相对E0改善27.94个百分点，最大回撤也从-45.14%改善到-26.87%。

但E1仍失败：

- 仅2/3窗口相对超额为正；
- 2022H2仍为-12.85%；
- leave-one-name为-1.24%；
- leave-one-sector为-9.95%。

E2负反应换股和E3负反应持有现金同样未通过窗口与leave-one稳定性门。

## 收敛认识

1. 新信息方向有效：市场对财报披露的开盘定价反应，比静态财务水平和同比增长更接近10日预测周期。
2. 当前失败发生在组合转换层，而不是组件层。
3. 低频事件不适合在每个固定再平衡日完全替代R0 Top1；下一轮应测试小比例、事件触发的卫星仓，而不是全量重排或简单现金化。
4. 下一轮仍只能使用校准期选择卫星仓规则；在通过架构门前不得打开2024–2025验证。

## 可复现性

- Price provider artifact: `8850463785`；
- PIT source artifact: `8926572265`；
- Calibration ledger artifact: `8927662386`；
- Fundamental event SHA256: `9d0babbf78a9a95272c15a94b56306194ff0a320d4fb92de4f7f78951fc7b8c7`；
- First complete evidence run: `31005748007`；
- Artifact: `8930269436`；
- Artifact digest: `sha256:a7ad01f89788962409571f69fecec993cad5bfc5f7ee97f2bbf44e8205e35f81`。
