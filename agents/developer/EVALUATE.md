# Alpha Engine: Multi-Dimensional Evaluation Framework (2026-PRO Edition)

## 0. 核心红线 (Production Redline) - **NEW**
- **Zero Placeholders**: 禁止在核心逻辑（回测、归因、账本、指标）中使用模拟数据。所有展示数据必须实时从 Qlib Artifacts、MLflow 或本地数据库提取。
- **Real Execution**: “Run Backtest” 必须真正触发训练/回测进程，且结果必须持久化并可追溯。
- **Data Integrity**: 必须处理真实市场的异常（如停牌、数据缺失），具备生产级的鲁棒性。

## 1. 策略表现 (Alpha Score)
- **Annualized Return**: 是否达到各市场基准 (CN: 15%, US: 20%)？
- **Sharpe Ratio**: 策略风险收益比是否优于 2.0？
- **Max Drawdown**: 是否严格控制在 15% 以内？
- **Turnover Rate**: 换手率是否在流动性可容忍范围内？

## 2. 工程成熟度 (Operational Excellence)
- **Environment Parity**: Host (Win/Linux) 与 Docker 的行为是否 100% 一致？
- **System Integrity**: API 是否具备 99.9% 的可用性？错误是否实时上报到“Thought Stream”？
- **Self-Healing**: 自动重试瞬态 API/数据失败。
- **Observability**: 每一笔交易、每一条日志是否可追溯、可审计？

## 3. 用户体验 (UX & Intelligence)
- **Glass Box Transparency**: 用户能否点击查看每一个模型的 YAML 配置、数据预处理逻辑？
- **Execution Ledger**: 在 Web UI 展示真实的持仓 (Holdings) 和交易过程 (Order logs)。
- **Profit Attribution**: 盈利来源是个股 Alpha、行业 Beta 还是因子暴露？
- **Agent Reasoning**: “Thought Stream” 是否真实反映了 Agent 的逻辑链条？

## 4. 评估矩阵 (The Matrix)
| 维度 | 指标 | 目标值 | 权重 |
| :--- | :--- | :--- | :--- |
| **Alpha** | Ann. Return | > 20% | 40% |
| **Reliability** | Successful Runs | 100% | 30% |
| **Transparency**| Audit Log Coverage | 100% | 20% |
| **Cognition** | Logic Traceability | High | 10% |
