# Research Configuration Reference

Alpha Engine 的 Python 研究流程可通过 `.env` 或进程环境覆盖少量配置。Research Artifact Studio 是静态 PWA，不读取 `.env`，也不需要服务地址或用户凭据。

## 安装

```bash
uv sync --extra dev
cp .env.example .env  # 仅在需要覆盖默认值时
```

## 研究目录

| Variable | Default | Purpose |
| --- | --- | --- |
| `TRADING_CONFIG_DIR` | `configs/` | 策略、研究规范和工作流配置 |
| `TRADING_DATA_DIR` | `data/` | 权威市场数据、数据治理产物和 durable research store |
| `TRADING_REPORTS_DIR` | `reports/` | 生成的研究报告 |
| `TRADING_SCRIPTS_DIR` | `scripts/` | 本地研究脚本 |
| `TRADING_ARTIFACTS_DIR` | `artifacts/` | 可删除的模型运行、构建、缓存和导出 staging |
| `TRADING_ASSISTANT_METADATA_DB_PATH` | `artifacts/metadata/metadata.db` | 可重建的本地查询缓存，不是权威数据源 |

相对路径以仓库根目录解析。`TRADING_ARTIFACTS_DIR` 下会派生 `mlruns/`、`models/`、`runs/`、`archives/` 和 `dashboard/`。删除整个 `artifacts/` 不得删除已经接受的研究历史。

## 数据权威边界

长期、可审计的数据与研究证据保存在 Git 跟踪的 `data/` 中：

- 市场数据及治理清单：`data/...`；
- 前端发布白名单：`data/research/catalog.json`；
- 接受后的训练/回测运行：`data/research/runs/<run_id>/`；
- 大型 Parquet 或模型二进制：仅在确有需要时使用 Git LFS，并在普通 Git manifest 中记录 SHA-256。

`artifacts/metadata/metadata.db` 仅用于本地索引、迁移和查询加速。模型、回测或绩效结论不得只存在于 SQLite 或短期 GitHub Actions artifact 中。

训练与回测的推荐流程：

1. 在 `artifacts/` 中生成 staging 输出；
2. 验证模型、数据快照、成本、窗口和文件哈希；
3. 通过 PR 将接受后的运行写入 `data/research/runs/`；
4. 更新 `data/research/catalog.json`；
5. Pages 从 repository research store 构建只读成果包。

## 风险和研究控制

| Variable | Default | Purpose |
| --- | --- | --- |
| `ALPHA_ENGINE_ENV` | `development` | Python 日志和运行环境标签 |
| `ALPHA_ENGINE_MAX_DRAWDOWN_THRESHOLD` | `0.15` | 回撤风控阻断阈值 |
| `SCORING_TIMEOUT_SEC` | `60` | 推理超时秒数 |
| `MAX_LEVERAGE` | `1.0` | 最大组合杠杆 |

回撤超过阈值时，`src.guardrails.risk_monitor` 返回阻断信号。调用方必须停止工作流或拒绝 promotion；不存在浏览器远程停止机制。

## 数据和研究集成

| Variable | Required when |
| --- | --- |
| `SEC_USER_AGENT` | 使用 SEC Company Facts 数据源 |
| `OPENAI_API_KEY` | 使用可选研究助手能力 |
| `DATABASE_URL` | 使用扩展分析数据库 |
| `TRADING_WEBHOOK_URL` | 发送工作流失败通知 |
| `ALPHA_DEVELOPER_TOKEN` | 保护独立 MCP JSON-RPC 工具 |

MCP 是单独的外部协议，不是前端数据源或浏览器执行通道。

## 成果包配置

默认从 repository research store 导出：

```bash
python scripts/export_static_site_data.py \
  --source repository \
  --repository-catalog data/research/catalog.json \
  --output artifacts/site/data
make research-bundle
```

浏览器边界固定为 `artifacts/research-bundle/alpha-engine-bundle.json`。manifest 外的文件不会被读取；文件大小、路径和 SHA-256 不匹配时加载失败。

本地 SQLite 仅作为显式迁移输入：

```bash
python scripts/export_static_site_data.py \
  --source metadata-db \
  --metadata-db artifacts/metadata/metadata.db
```

## 验证

```bash
make doctor
make test
make ci
```

提交前确认：

1. `.env` 和密钥未提交；
2. 数据、模型、基准和股票池 identity 已进入 manifest；
3. 接受后的训练/回测证据已进入 `data/research/`，而不是只留在 `artifacts/`；
4. 成果包可从干净 checkout 重复导出；
5. `research_only=true`、`trade_ready=false`；
6. 浏览器没有网络取数、任务执行或写操作。
