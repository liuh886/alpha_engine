# CN130 极端尾部、行业分层与因子族探索报告

> CN130成员、10日预测周期和2026-08-03 provider保持不变。2026H1与2026H2_PARTIAL仅用于报告。

## 执行身份

- Provider identity: `abae71f037571a9a847d4582e0bea9fabdd71796cac54a70aa7c6d07b668eeb0`
- Universe SHA256: `4ce5b95e60d38a13e4852fb6f7a3a6437b55d6da0fb317ad553d114e85158529`
- Classification SHA256: `d1ef3bd06c0953c7e78fa0ba99c372da714ddce67203909d195d73e9eec61d15`
- `research_only=true`; `trade_ready=false`。

## Stage A：冻结分数尾部组合

| 排序来源 | 特征族 | 组合 | 20bps相对超额 | 最大回撤 | 正窗口 | Precision@K | 名称集中 | 行业集中 | 留一名称 | 留一行业 | 40bps超额 | Gate |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| r2_industry_relative_rank | momentum_reversal | global_top5_sector_cap2 | 106.80% | -17.71% | 3/4 | 52.8% | 6.7% | 48.6% | 68.73% | 19.33% | 90.82% | PASS |
| r2_industry_relative_rank | current_cn_ohlcv | global_top8 | 71.82% | -29.50% | 4/4 | 50.7% | 8.4% | 52.8% | 45.00% | 21.87% | 59.45% | PASS |
| r2_industry_relative_rank | momentum_reversal | sector_5x1 | 67.36% | -20.41% | 3/4 | 50.0% | 8.1% | 46.0% | 43.62% | 7.36% | 53.70% | PASS |
| r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | sector_4x1 | 67.34% | -18.38% | 4/4 | 50.5% | 7.9% | 35.9% | 52.59% | 24.35% | 53.59% | PASS |
| r4_two_stage_hierarchical_rank | momentum_reversal | global_top5 | 60.23% | -21.36% | 3/4 | 51.6% | 9.0% | 43.2% | 36.63% | 24.30% | 47.66% | PASS |
| r4_two_stage_hierarchical_rank | momentum_reversal | global_top5_sector_cap1 | 60.23% | -21.36% | 3/4 | 51.6% | 9.0% | 43.2% | 36.63% | 24.30% | 47.66% | PASS |
| r4_two_stage_hierarchical_rank | momentum_reversal | global_top5_sector_cap2 | 60.23% | -21.36% | 3/4 | 51.6% | 9.0% | 43.2% | 36.63% | 24.30% | 47.66% | PASS |
| r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top8 | 52.09% | -19.17% | 3/4 | 48.8% | 5.9% | 39.5% | 38.25% | 28.92% | 41.19% | PASS |
| r2_industry_relative_rank | current_cn_ohlcv | global_top15 | 50.75% | -27.86% | 3/4 | 49.1% | 6.0% | 46.4% | 40.63% | 20.93% | 41.55% | PASS |
| r2_industry_relative_rank | current_cn_ohlcv | global_top5_sector_cap1 | 50.21% | -23.68% | 3/4 | 50.0% | 10.0% | 28.3% | 27.31% | 20.66% | 38.25% | PASS |
| r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | sector_5x1 | 42.09% | -17.90% | 4/4 | 50.0% | 6.9% | 32.6% | 31.70% | 9.67% | 30.56% | PASS |
| r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top10 | 40.19% | -21.20% | 4/4 | 49.2% | 5.5% | 43.9% | 36.89% | 17.95% | 30.35% | PASS |
| r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top15 | 32.61% | -21.60% | 4/4 | 47.6% | 5.5% | 46.9% | 30.64% | 12.20% | 24.12% | PASS |
| r4_two_stage_hierarchical_rank | momentum_reversal | global_top8 | 32.27% | -19.87% | 3/4 | 49.8% | 7.1% | 34.5% | 26.45% | 9.95% | 22.28% | PASS |
| r2_industry_relative_rank | current_cn_ohlcv | sector_3x2 | 30.84% | -26.65% | 3/4 | 48.3% | 8.0% | 49.0% | 12.08% | 4.42% | 20.49% | PASS |
| r2_industry_relative_rank | current_cn_ohlcv | sector_3x1 | 30.26% | -25.44% | 3/4 | 51.3% | 11.3% | 41.9% | 8.55% | 19.95% | 19.37% | PASS |
| r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top5_sector_cap2 | 24.78% | -22.03% | 3/4 | 47.2% | 7.4% | 39.3% | 17.43% | 13.40% | 14.93% | PASS |
| r2_industry_relative_rank | current_cn_ohlcv | global_top5_sector_cap2 | 21.18% | -32.83% | 3/4 | 48.0% | 9.0% | 48.0% | 32.50% | 25.98% | 11.30% | PASS |
| r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | sector_3x1 | 21.17% | -24.47% | 4/4 | 48.0% | 9.4% | 38.4% | 12.83% | 31.01% | 11.02% | PASS |
| r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | sector_3x2 | 14.18% | -25.17% | 4/4 | 48.3% | 5.6% | 43.7% | 6.04% | 33.24% | 5.21% | PASS |
| r2_industry_relative_rank | momentum_reversal | sector_3x1 | 94.09% | -26.18% | 3/4 | 51.3% | 10.6% | 55.7% | 49.08% | 6.07% | 77.80% | FAIL |
| r4_two_stage_hierarchical_rank | momentum_reversal | sector_3x1 | 77.42% | -27.54% | 3/4 | 50.7% | 11.5% | 68.7% | 36.27% | -7.91% | 63.03% | FAIL |
| r2_industry_relative_rank | momentum_reversal | global_top5_sector_cap1 | 57.15% | -21.25% | 2/4 | 50.0% | 8.1% | 49.8% | 33.39% | 0.04% | 44.67% | FAIL |
| r2_industry_relative_rank | current_cn_ohlcv | global_top10 | 57.07% | -29.36% | 4/4 | 49.8% | 6.2% | 55.0% | 46.33% | 40.16% | 46.32% | FAIL |
| r2_industry_relative_rank | momentum_reversal | sector_4x1 | 51.96% | -24.42% | 2/4 | 49.5% | 8.8% | 51.3% | 24.04% | 22.60% | 39.25% | FAIL |
| r4_two_stage_hierarchical_rank | momentum_reversal | sector_3x2 | 49.91% | -21.12% | 2/4 | 48.7% | 6.9% | 62.6% | 40.93% | -2.27% | 38.30% | FAIL |
| r2_industry_relative_rank | momentum_reversal | sector_3x2 | 46.73% | -22.59% | 2/4 | 47.7% | 6.1% | 53.8% | 37.82% | 20.18% | 34.97% | FAIL |
| r2_industry_relative_rank | current_cn_ohlcv | global_top5 | 45.91% | -31.82% | 3/4 | 48.4% | 12.2% | 68.7% | 16.50% | -1.17% | 34.10% | FAIL |
| r2_industry_relative_rank | current_cn_ohlcv | sector_4x1 | 45.04% | -24.57% | 2/4 | 52.5% | 9.4% | 37.9% | 26.29% | 6.43% | 33.08% | FAIL |
| r2_industry_relative_rank | momentum_reversal | global_top8 | 43.36% | -28.38% | 2/4 | 48.2% | 5.6% | 36.3% | 33.54% | 24.89% | 32.74% | FAIL |
| r4_two_stage_hierarchical_rank | momentum_reversal | sector_4x1 | 42.39% | -22.98% | 3/4 | 48.0% | 10.2% | 65.0% | 16.25% | -15.72% | 30.84% | FAIL |
| r2_industry_relative_rank | momentum_reversal | global_top15 | 33.18% | -20.39% | 2/4 | 49.1% | 4.3% | 42.2% | 30.49% | 18.61% | 24.03% | FAIL |
| r2_industry_relative_rank | momentum_reversal | global_top5 | 31.39% | -31.09% | 2/4 | 48.8% | 8.8% | 37.1% | 13.42% | 20.56% | 21.09% | FAIL |
| r4_two_stage_hierarchical_rank | momentum_reversal | global_top10 | 29.89% | -18.33% | 3/4 | 48.8% | 6.1% | 41.1% | 22.47% | -1.28% | 20.52% | FAIL |
| r2_industry_relative_rank | momentum_reversal | global_top10 | 29.62% | -25.23% | 2/4 | 48.2% | 5.7% | 34.8% | 17.05% | 23.25% | 20.04% | FAIL |
| r4_two_stage_hierarchical_rank | momentum_reversal | global_top3 | 25.93% | -28.92% | 2/4 | 48.7% | 9.9% | 65.4% | 6.55% | -12.54% | 15.71% | FAIL |
| r2_industry_relative_rank | current_cn_ohlcv | sector_5x1 | 24.30% | -22.99% | 2/4 | 50.4% | 8.8% | 41.0% | 11.05% | -0.02% | 14.09% | FAIL |
| r4_two_stage_hierarchical_rank | momentum_reversal | sector_5x1 | 21.77% | -24.77% | 2/4 | 46.0% | 9.5% | 65.5% | 3.25% | -15.03% | 12.25% | FAIL |
| r4_two_stage_hierarchical_rank | momentum_reversal | global_top15 | 17.58% | -20.36% | 2/4 | 46.9% | 4.7% | 39.2% | 12.80% | -1.91% | 9.13% | FAIL |
| r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top5_sector_cap1 | 15.71% | -18.35% | 3/4 | 46.0% | 6.9% | 42.5% | 3.78% | -5.70% | 6.46% | FAIL |
| r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top5 | 15.62% | -24.84% | 3/4 | 46.8% | 8.4% | 39.8% | 13.64% | -4.76% | 6.61% | FAIL |
| r2_industry_relative_rank | momentum_reversal | global_top3 | 15.50% | -30.46% | 2/4 | 42.7% | 10.1% | 59.9% | -9.91% | 39.16% | 6.07% | FAIL |
| r2_industry_relative_rank | current_cn_ohlcv | global_top3 | -15.53% | -37.67% | 1/4 | 46.7% | 8.2% | 58.7% | -24.49% | 87.95% | -22.71% | FAIL |
| r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top3 | -20.53% | -31.59% | 1/4 | 42.7% | 8.7% | 33.2% | -31.96% | -40.14% | -27.13% | FAIL |

## 2026报告窗口（不参与选择）

| 窗口 | 排序来源 | 特征族 | 组合 | 相对超额 | 最大回撤 | Precision@K |
|---|---|---|---|---:|---:|---:|
| 2026H1 | r2_industry_relative_rank | momentum_reversal | sector_3x1 | 70.86% | -21.63% | 63.9% |
| 2026H1 | r2_industry_relative_rank | momentum_reversal | global_top10 | 66.49% | -11.84% | 60.8% |
| 2026H1 | r4_two_stage_hierarchical_rank | momentum_reversal | sector_3x1 | 65.19% | -21.63% | 63.9% |
| 2026H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | sector_3x1 | 49.87% | -34.33% | 63.9% |
| 2026H1 | r2_industry_relative_rank | momentum_reversal | global_top15 | 49.71% | -12.14% | 56.7% |
| 2026H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top3 | 49.28% | -30.45% | 55.6% |
| 2026H1 | r2_industry_relative_rank | momentum_reversal | sector_4x1 | 43.90% | -16.22% | 60.4% |
| 2026H1 | r2_industry_relative_rank | momentum_reversal | global_top8 | 43.60% | -12.88% | 58.3% |
| 2026H1 | r2_industry_relative_rank | current_cn_ohlcv | global_top3 | 42.91% | -27.67% | 55.6% |
| 2026H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top5 | 40.30% | -27.44% | 58.3% |
| 2026H1 | r2_industry_relative_rank | momentum_reversal | global_top5 | 37.67% | -13.37% | 56.7% |
| 2026H1 | r2_industry_relative_rank | current_cn_ohlcv | global_top15 | 36.56% | -14.33% | 51.1% |
| 2026H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top10 | 36.10% | -18.73% | 57.5% |
| 2026H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | sector_3x2 | 34.15% | -31.15% | 59.7% |
| 2026H1 | r2_industry_relative_rank | current_cn_ohlcv | global_top10 | 32.58% | -18.83% | 50.8% |
| 2026H1 | r2_industry_relative_rank | current_cn_ohlcv | global_top5 | 32.26% | -25.51% | 53.3% |
| 2026H1 | r4_two_stage_hierarchical_rank | momentum_reversal | sector_4x1 | 31.72% | -15.81% | 52.1% |
| 2026H1 | r2_industry_relative_rank | momentum_reversal | global_top5_sector_cap2 | 29.87% | -16.41% | 53.3% |
| 2026H1 | r2_industry_relative_rank | current_cn_ohlcv | global_top8 | 29.59% | -25.64% | 51.0% |
| 2026H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top15 | 27.69% | -15.39% | 53.9% |
| 2026H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top8 | 26.95% | -25.89% | 56.2% |
| 2026H1 | r2_industry_relative_rank | momentum_reversal | global_top5_sector_cap1 | 24.92% | -18.64% | 53.3% |
| 2026H1 | r2_industry_relative_rank | momentum_reversal | sector_5x1 | 23.57% | -16.05% | 53.3% |
| 2026H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top5_sector_cap2 | 22.29% | -34.43% | 51.7% |
| 2026H1 | r2_industry_relative_rank | momentum_reversal | sector_3x2 | 21.03% | -18.75% | 51.4% |
| 2026H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | sector_4x1 | 20.03% | -33.98% | 54.2% |
| 2026H1 | r2_industry_relative_rank | momentum_reversal | global_top3 | 19.42% | -18.13% | 50.0% |
| 2026H1 | r4_two_stage_hierarchical_rank | momentum_reversal | sector_3x2 | 19.29% | -18.75% | 51.4% |
| 2026H1 | r4_two_stage_hierarchical_rank | momentum_reversal | global_top15 | 15.18% | -7.74% | 48.9% |
| 2026H1 | r4_two_stage_hierarchical_rank | momentum_reversal | sector_5x1 | 14.73% | -14.38% | 46.7% |
| 2026H1 | r2_industry_relative_rank | current_cn_ohlcv | global_top5_sector_cap2 | 12.33% | -33.82% | 53.3% |
| 2026H1 | r2_industry_relative_rank | current_cn_ohlcv | sector_3x1 | 11.96% | -40.49% | 44.4% |
| 2026H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | sector_5x1 | 8.52% | -30.73% | 51.7% |
| 2026H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top5_sector_cap1 | 6.27% | -29.20% | 46.7% |
| 2026H1 | r2_industry_relative_rank | current_cn_ohlcv | sector_4x1 | 5.98% | -38.53% | 43.8% |
| 2026H1 | r2_industry_relative_rank | current_cn_ohlcv | sector_3x2 | 4.88% | -33.30% | 50.0% |
| 2026H1 | r4_two_stage_hierarchical_rank | momentum_reversal | global_top8 | 3.74% | -11.06% | 47.9% |
| 2026H1 | r4_two_stage_hierarchical_rank | momentum_reversal | global_top10 | 2.30% | -12.91% | 45.8% |
| 2026H1 | r4_two_stage_hierarchical_rank | momentum_reversal | global_top5 | 2.29% | -15.10% | 46.7% |
| 2026H1 | r4_two_stage_hierarchical_rank | momentum_reversal | global_top5_sector_cap1 | 2.29% | -15.10% | 46.7% |
| 2026H1 | r4_two_stage_hierarchical_rank | momentum_reversal | global_top5_sector_cap2 | 2.29% | -15.10% | 46.7% |
| 2026H1 | r4_two_stage_hierarchical_rank | momentum_reversal | global_top3 | -2.48% | -23.12% | 41.7% |
| 2026H1 | r2_industry_relative_rank | current_cn_ohlcv | sector_5x1 | -3.45% | -36.22% | 43.3% |
| 2026H1 | r2_industry_relative_rank | current_cn_ohlcv | global_top5_sector_cap1 | -4.46% | -36.25% | 43.3% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | momentum_reversal | global_top3 | 17.13% | 0.00% | 83.3% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | momentum_reversal | global_top5 | 11.97% | -0.25% | 80.0% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | momentum_reversal | global_top5_sector_cap1 | 11.97% | -0.25% | 80.0% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | momentum_reversal | global_top5_sector_cap2 | 11.97% | -0.25% | 80.0% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | momentum_reversal | global_top8 | 9.94% | -1.48% | 81.2% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | momentum_reversal | global_top10 | 7.58% | -0.43% | 80.0% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | momentum_reversal | sector_5x1 | 2.69% | -3.22% | 80.0% |
| 2026H2_PARTIAL | r2_industry_relative_rank | momentum_reversal | global_top5_sector_cap1 | 1.69% | -3.26% | 80.0% |
| 2026H2_PARTIAL | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | sector_5x1 | 1.46% | -7.32% | 60.0% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | momentum_reversal | sector_4x1 | 1.06% | -3.37% | 75.0% |
| 2026H2_PARTIAL | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | sector_4x1 | 0.80% | -6.47% | 62.5% |
| 2026H2_PARTIAL | r2_industry_relative_rank | current_cn_ohlcv | sector_4x1 | 0.26% | -6.97% | 62.5% |
| 2026H2_PARTIAL | r2_industry_relative_rank | current_cn_ohlcv | sector_3x1 | 0.22% | -5.73% | 66.7% |
| 2026H2_PARTIAL | r2_industry_relative_rank | current_cn_ohlcv | global_top5_sector_cap1 | 0.17% | -5.86% | 60.0% |
| 2026H2_PARTIAL | r2_industry_relative_rank | current_cn_ohlcv | sector_5x1 | 0.17% | -5.86% | 60.0% |
| 2026H2_PARTIAL | r2_industry_relative_rank | momentum_reversal | sector_5x1 | -0.69% | -5.52% | 70.0% |
| 2026H2_PARTIAL | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top5_sector_cap1 | -1.39% | -7.32% | 50.0% |
| 2026H2_PARTIAL | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | sector_3x1 | -2.38% | -8.17% | 50.0% |
| 2026H2_PARTIAL | r2_industry_relative_rank | momentum_reversal | sector_4x1 | -3.37% | -5.56% | 75.0% |
| 2026H2_PARTIAL | r2_industry_relative_rank | current_cn_ohlcv | global_top5_sector_cap2 | -4.33% | -8.36% | 60.0% |
| 2026H2_PARTIAL | r2_industry_relative_rank | current_cn_ohlcv | sector_3x2 | -4.60% | -7.31% | 58.3% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | momentum_reversal | global_top15 | -6.76% | -6.89% | 56.7% |
| 2026H2_PARTIAL | r2_industry_relative_rank | momentum_reversal | sector_3x1 | -7.45% | -6.55% | 66.7% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | momentum_reversal | sector_3x1 | -7.45% | -6.55% | 66.7% |
| 2026H2_PARTIAL | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top5_sector_cap2 | -8.15% | -10.74% | 50.0% |
| 2026H2_PARTIAL | r2_industry_relative_rank | current_cn_ohlcv | global_top3 | -8.24% | -5.73% | 50.0% |
| 2026H2_PARTIAL | r2_industry_relative_rank | momentum_reversal | global_top5_sector_cap2 | -11.35% | -9.06% | 50.0% |
| 2026H2_PARTIAL | r2_industry_relative_rank | current_cn_ohlcv | global_top5 | -11.99% | -8.36% | 50.0% |
| 2026H2_PARTIAL | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | sector_3x2 | -13.04% | -10.26% | 41.7% |
| 2026H2_PARTIAL | r2_industry_relative_rank | current_cn_ohlcv | global_top8 | -14.82% | -12.92% | 43.8% |
| 2026H2_PARTIAL | r2_industry_relative_rank | momentum_reversal | sector_3x2 | -16.58% | -9.70% | 41.7% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | momentum_reversal | sector_3x2 | -16.58% | -9.70% | 41.7% |
| 2026H2_PARTIAL | r2_industry_relative_rank | current_cn_ohlcv | global_top10 | -17.86% | -13.38% | 40.0% |
| 2026H2_PARTIAL | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top15 | -19.04% | -16.48% | 33.3% |
| 2026H2_PARTIAL | r2_industry_relative_rank | current_cn_ohlcv | global_top15 | -19.57% | -15.58% | 30.0% |
| 2026H2_PARTIAL | r2_industry_relative_rank | momentum_reversal | global_top10 | -20.23% | -14.36% | 35.0% |
| 2026H2_PARTIAL | r2_industry_relative_rank | momentum_reversal | global_top15 | -20.27% | -13.96% | 33.3% |
| 2026H2_PARTIAL | r2_industry_relative_rank | momentum_reversal | global_top8 | -20.57% | -13.99% | 31.2% |
| 2026H2_PARTIAL | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top3 | -22.81% | -18.59% | 33.3% |
| 2026H2_PARTIAL | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top5 | -23.13% | -19.89% | 30.0% |
| 2026H2_PARTIAL | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top10 | -23.41% | -19.67% | 30.0% |
| 2026H2_PARTIAL | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | global_top8 | -24.50% | -20.37% | 31.2% |
| 2026H2_PARTIAL | r2_industry_relative_rank | momentum_reversal | global_top5 | -26.30% | -9.06% | 20.0% |
| 2026H2_PARTIAL | r2_industry_relative_rank | momentum_reversal | global_top3 | -27.93% | -8.68% | 16.7% |

## Stage B：单因子与因子族

### 单因子前20

| 因子 | 模式 | 因子族 | Mean Rank IC | 正窗口 | 最差窗口 | 增量IC | Mean Spread | LOO最小值 | Gate |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| intraday_range_20 | sector_relative | risk_quality | 0.0162 | 3/4 | -0.0732 | 0.0173 | -0.72% | -0.0026 | FAIL |
| distance_low_20 | global | breakout_position | 0.0147 | 3/4 | -0.0720 | 0.0217 | 0.89% | -0.0035 | FAIL |
| recovery_from_low_20 | global | drawdown_recovery | 0.0147 | 3/4 | -0.0720 | 0.0217 | 0.89% | -0.0035 | FAIL |
| volatility_60 | sector_relative | risk_quality | 0.0137 | 2/4 | -0.0881 | 0.0151 | -0.81% | -0.0127 | FAIL |
| reversal_3 | global | short_reversal | 0.0131 | 3/4 | -0.0374 | 0.0066 | 0.03% | -0.0031 | FAIL |
| trend_efficiency_20 | sector_relative | trend_momentum | 0.0123 | 3/4 | -0.0156 | 0.0131 | 0.35% | 0.0063 | FAIL |
| idiosyncratic_volatility_60 | sector_relative | risk_quality | 0.0117 | 2/4 | -0.0692 | 0.0130 | -0.73% | -0.0102 | FAIL |
| distance_low_20 | sector_relative | breakout_position | 0.0105 | 2/4 | -0.0388 | 0.0157 | 0.65% | -0.0042 | FAIL |
| recovery_from_low_20 | sector_relative | drawdown_recovery | 0.0105 | 2/4 | -0.0388 | 0.0157 | 0.65% | -0.0042 | FAIL |
| amount_stability_20 | global | liquidity | 0.0104 | 2/4 | -0.0331 | 0.0027 | -0.21% | -0.0073 | FAIL |
| momentum_10 | sector_relative | trend_momentum | 0.0104 | 2/4 | -0.0178 | 0.0191 | 0.34% | -0.0074 | FAIL |
| momentum_10 | global | trend_momentum | 0.0100 | 3/4 | -0.0354 | 0.0214 | 0.42% | -0.0079 | FAIL |
| reversal_3 | sector_relative | short_reversal | 0.0095 | 2/4 | -0.0148 | 0.0041 | -0.12% | 0.0017 | FAIL |
| intraday_range_20 | global | risk_quality | 0.0071 | 3/4 | -0.1336 | 0.0084 | -0.92% | -0.0192 | FAIL |
| reversal_5 | global | short_reversal | 0.0070 | 2/4 | -0.0463 | 0.0006 | -0.15% | -0.0131 | FAIL |
| amihud_20 | sector_relative | liquidity | 0.0068 | 1/4 | -0.0285 | 0.0063 | -0.37% | -0.0141 | FAIL |
| amihud_20 | global | liquidity | 0.0067 | 1/4 | -0.0231 | 0.0072 | -0.50% | -0.0168 | FAIL |
| volatility_10 | sector_relative | risk_quality | 0.0057 | 2/4 | -0.0536 | 0.0070 | -0.66% | -0.0071 | FAIL |
| downside_volatility_60 | sector_relative | risk_quality | 0.0056 | 2/4 | -0.0906 | 0.0087 | -0.77% | -0.0220 | FAIL |
| idiosyncratic_volatility_60 | global | risk_quality | 0.0052 | 3/4 | -0.1358 | 0.0058 | -1.04% | -0.0211 | FAIL |

### 因子族组合

| 因子族 | 模式 | 成员数 | Mean Rank IC | 正窗口 | 最差窗口 | 增量IC | Mean Spread | Gate |
|---|---|---:|---:|---:|---:|---:|---:|---|
| liquidity | global | 2 | 0.0116 | 1/4 | -0.0361 | 0.0062 | -0.24% | FAIL |
| risk_quality | sector_relative | 7 | 0.0111 | 2/4 | -0.0794 | 0.0127 | -1.00% | FAIL |
| short_reversal | global | 3 | 0.0086 | 2/4 | -0.0469 | 0.0026 | -0.08% | FAIL |
| liquidity | sector_relative | 2 | 0.0050 | 1/4 | -0.0260 | 0.0000 | -0.30% | FAIL |
| short_reversal | sector_relative | 3 | 0.0049 | 2/4 | -0.0245 | -0.0007 | -0.09% | FAIL |
| breakout_position | sector_relative | 5 | 0.0017 | 2/4 | -0.0557 | 0.0135 | 0.30% | FAIL |
| drawdown_recovery | sector_relative | 4 | 0.0002 | 2/4 | -0.0717 | 0.0094 | 0.28% | FAIL |
| trend_momentum | sector_relative | 9 | -0.0014 | 2/4 | -0.0702 | 0.0068 | 0.29% | FAIL |
| risk_quality | global | 7 | -0.0040 | 2/4 | -0.1410 | -0.0043 | -1.29% | FAIL |
| relative_strength | sector_relative | 2 | -0.0047 | 2/4 | -0.0579 | 0.0056 | 0.44% | FAIL |
| breakout_position | global | 5 | -0.0051 | 2/4 | -0.0818 | 0.0099 | 0.29% | FAIL |
| trend_momentum | global | 9 | -0.0059 | 2/4 | -0.1058 | 0.0042 | 0.45% | FAIL |
| volume_price | global | 5 | -0.0077 | 2/4 | -0.0301 | -0.0062 | 0.22% | FAIL |
| drawdown_recovery | global | 4 | -0.0093 | 2/4 | -0.1060 | 0.0023 | 0.21% | FAIL |
| volume_price | sector_relative | 5 | -0.0116 | 2/4 | -0.0375 | -0.0103 | 0.04% | FAIL |
| relative_strength | global | 2 | -0.0137 | 2/4 | -0.0911 | -0.0019 | 0.29% | FAIL |

## 最终裁决

- Decision: `tail_signal_supported_factor_rebuild_required`
- Tail signal supported: True
- Factor model rebuild authorized: False
- Supported factor IDs: none
- Supported family IDs: none
- 本研究不会自动创建或晋级CN x1.1。

## 解释边界

- Stage A使用冻结分数，只检验极端尾部与行业分散是否有经济意义。
- Stage B只按IC、稳定性、增量信息与冗余筛选，不使用最终组合收益挑因子。
- 静态精选池存在生存者偏差；PIT市值与基本面仍未覆盖。
