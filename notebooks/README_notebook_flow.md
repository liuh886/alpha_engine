# Notebook 流程说明

## 完整数据流

```text
00_data_download_and_sync.ipynb
  └─ 输出: data/session_config.json          ← 全局共享配置
         data/csv_source/<SYM>.csv

01_factor_research.ipynb
  ├─ 输入: data/session_config.json
  └─ 输出: data/factor_selection.json        ← 因子筛选结果

end_to_end_training_pipeline.ipynb
  ├─ 输入: data/session_config.json
  │         data/factor_selection.json       ← 若存在则用，否则用 Alpha158 全集
  └─ 输出: artifacts/<id>/model.pkl
           SQLite 模型注册表
           dashboard.json

02_strategy_validation.ipynb / 02_signal_validation.ipynb
  ├─ 输入: data/session_config.json
  │         SQLite 模型注册表或显式模型路径
  └─ 输出: data/validated_scores.parquet     ← 信号验证结果
           data/signal_validation_summary.json

03_topn_spread_research.ipynb
  ├─ 输入: data/session_config.json
  │         data/validated_scores.parquet    ← 直接读取，无需重加载模型
  └─ 输出: data/spread_scan_results.csv

05_model_registry_explorer.ipynb
  ├─ 输入: data/session_config.json
  │         SQLite + validated_scores.parquet
  └─ 操作: 并排对比 / IC 衰减分析 / 晋级 PRODUCTION
```

## 使用原则

- **一次配置，全程共用：** 只在 `00` 里修改 `MARKET` / `SYMBOLS` / `BENCHMARK` / `MODEL_TAG` 等配置，后续 notebook 应读取 `data/session_config.json`。
- **中间产物显式落盘：** 每个 notebook 都应有明确输出文件，下一个 notebook 直接读取，避免重复下载、重复加载模型、重复生成特征。
- **黑盒变接口：** 核心逻辑应通过 `src.core.*` 暴露为可调用函数，例如 `generate_scores`、`select_topk`、`select_bottomk`、`build_rolling_portfolio`、`compute_spread`。
- **02 → 03 不重复加载：** 信号验证 notebook 产出 `validated_scores.parquet` 后，spread 研究 notebook 应直接读取该文件。
- **先定义契约，再迁移 notebook：** notebook JSON diff 很难 review，后续应按 notebook 单独迁移，不要一次性重写整条链路。

## 建议迁移顺序

1. `00_data_download_and_sync.ipynb`：写出 `data/session_config.json`。
2. `01_factor_research.ipynb`：读取 `session_config.json`，写出 `data/factor_selection.json`。
3. `end_to_end_training_pipeline.ipynb`：优先读取 `factor_selection.json`，缺失时回退到默认 Alpha158 全集。
4. `02_*validation.ipynb`：读取模型注册表或显式模型路径，写出 `validated_scores.parquet`。
5. `03_topn_spread_research.ipynb`：只读取 `validated_scores.parquet` 和收益数据，不重复生成模型分数。
6. `05_model_registry_explorer.ipynb`：读取统一 config 和验证产物，做模型对比与晋级。

## 切换市场

只需修改 `00_data_download_and_sync.ipynb` 的 session 配置并重新运行。后续 notebook 不应再单独维护一份 MARKET/SYMBOLS。

```python
MARKET = "cn"              # us / cn / hk
SYMBOLS = ["600519.SH"]
BENCHMARK = "000300"
MODEL_TAG = f"{MARKET}_baseline"
```

## Release 产物契约

正式发布的运行路径是 `scripts/generate_release_candidate.py`（而非 notebook）。Notebook 链路用于研究和原型验证，其产物结构与 release 脚本保持一致：

| 产物 | 位置 | 用途 |
|---|---|---|
| `session_config.json` | `data/session_config.json` | 全局共享配置（市场、标的、基准、时间段） |
| `validated_scores.parquet` | `data/validated_scores.parquet` | 信号验证分数，供 spread 分析直接消费 |
| `release_manifest.json` | `artifacts/release_candidate/{candidate}/release_manifest.json` | Release 成功后的完整清单 |
| `release_failure_report.json` | `artifacts/release_candidate/{candidate}/release_failure_report.json` | Release 失败时的诊断报告 |

### 一条烟雾路径：config → spread

```
session_config.json  ──→  end_to_end_training_pipeline.ipynb
                              │
                              ├── 训练（LGBMRegressor, Alpha158 特征）
                              └── 输出 model.pkl / predictions.csv / labels.csv
                                   │
                                   ↓
02_signal_validation.ipynb  ──→  validated_scores.parquet
                                   │
                                   ↓
03_topn_spread_research.ipynb  ──→  spread_scan_results.csv
```

### Notebook 不应重复核心逻辑

`scripts/generate_release_candidate.py` 是唯一完整的 release pipeline 入口。Notebook 应直接引用其产物（`validated_scores.parquet`、`diagnostics.json`）而非重新实现 Qlib 初始化、walk-forward、backtest 等流程。研究期的 notebook 可以跳过 release 的门禁检查（snapshot quality、frontend build），但最终的正式运行必须通过 `generate_release_candidate.py` 完成。如需在 notebook 中快速回查 release 结果，读取 `release_manifest.json` 中 `walk_forward` 和 `backtest` 摘要段即可。
