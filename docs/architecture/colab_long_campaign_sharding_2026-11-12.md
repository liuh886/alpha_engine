# Colab 长实验分片执行（P2 · Campaign Sharding）

## 架构决策 · 2026-11-12

Owner 的新优先级是 **实验任务下放与长时间可恢复执行**。停止以 CPU2/CPU4
进程扩展作为平台 P0。C0 的 2026-11-12 FINAL 已完成 Colab 实测、归档初核；
独立数据/数值审核仍由本地 Agent 在 #1373 接手。

> **本 PR 交付的是确定性分片编排与 canonical E2 runner 的单分片过滤，
> 不是一份已获准运行的新 C1 模型实验。** 当前
> `configs/research_experiments/c1_us73_research_queue_20261108_v1.json`
> 仍是 `NOT_EXECUTABLE`，缺新特征和模型 adapter、数据时点合同及独立筛查。
> 不可将其冒充现有可运行批次。

### 不引入新的算力模型

本地 Agent 是**编排方**，Google Drive 是**批次交换介质**，Colab
是**Owner 显式打开的独立交互式计算会话**，本地 Agent 最后做**独立审核与合并**。
不使用 webhook/代理/SSH、自动创建云实例、后台任务 daemon 或第二套训练器；
每个会话仍由同一原有 Study Workspace/研究模拟器完成一个试验。

```text
本地 Agent
  └─ preflight → freeze runner/source/spec
     └─ compile_shards → manifest(s01, s02, s03)
        ├─ Colab A: s01 → /content/s01/runs → checkpoint A.zip
        ├─ Colab B: s02 → /content/s02/runs → checkpoint B.zip
        └─ Colab C: s03 → /content/s03/runs → checkpoint C.zip
            ↓
        私有 Drive incoming_unreviewed/<campaign>/<shard>/<session>/
            ↓
本地 Agent: archive SHA+inner index+trial ID+per-trial receipt numeric audit
            ↓
ChatGPT: 跨折审查、成本/时点/基线对照和下一阶段 GO/NO-GO
```

### 本次已提供的程序接口

```bash
# Local Agent: 一次性生成固定完整分片分配，不发生模型训练。
python -m src.research.colab_campaign_shards create \
  --batch-spec /private/frozen/batch.json \
  --shard-count 3 \
  --manifest /private/frozen/shards.json

# 独立复查源码、runner、数据和分片身份。
python -m src.research.colab_campaign_shards verify \
  --batch-spec /private/frozen/batch.json \
  --manifest /private/frozen/shards.json

# Colab A（人工打开的会话；仅一进程/一个分片）。
# /content/s01/runs 与 s02/s03 的工作目录必须完全不同。
python -m src.research.colab_experiment_batch run \
  --batch-spec /content/job/batch.json \
  --data-root /content/isolated_price_source \
  --output-root /content/s01/runs \
  --shard-manifest /content/job/shards.json \
  --shard-id s01 \
  --max-new-trials 6 \
  --max-wall-seconds 6600

# 每完成一个受限 chunk，原 runner 的 checkpoint-archive 只写这个分片
# 的已持久化实验结果。之后把 ZIP + 外部 SHA 写入本分片私有 Drive 目录；
# 再执行同一 shard 的下一 chunk，指定 --resume。
python -m src.research.colab_experiment_batch checkpoint-archive \
  --batch-spec /content/job/batch.json \
  --data-root /content/isolated_price_source \
  --output-root /content/s01/runs \
  --archive /content/s01/checkpoint-0001.zip
```

这些 CLI 是**给本地 Agent 的封装原语**，不是要求 Owner 自行编辑命令。
待 C1 的独立新批次经过可运行验收，Agent 应生成
`AlphaEngine/Colab_Campaign_A.ipynb`、`..._B.ipynb` 等**各自固定 s01/s02**
的可直接 Run All Notebook，一份 Notebook 对应一个不可变分片。
用户只需打开需要的窗口、运行全部并授权 Drive。

### 中断、恢复与并发语义

- **确定性完整分配**：按 trial ID 排序、round robin 分配，分片之间不重叠，
  完整覆盖冻结研究批次。这个规则不能根据收益或 fold 表现调整。
- **研究与数据身份不变**：原 `batch_spec_sha256`、`runner_git_sha`、
  `history_archive_sha256` 等必须与执行器原始合同一致。Shard manifest
  校验失败不得执行。修改训练代码需要新 `runner_git_sha` 和新批次身份，
  **不能把历史 261/288 项重新跑作新的研究证据**。
- **一个窗口一个 writer**：独立 `/content/sNN/runs`、Drive 唯一
  `campaign/shard/session` 目录；严禁多个窗口操作同一 `output_root`、
  共享 feature-cache 或共同编辑结果文件。
- **定期持久化**：现有 runner 每个 trial 原子保存回执，chunk 完成后保存
  严格索引的 ZIP；检查点不可覆盖。Colab VM 消失会丢失自上个 Drive
  检查点之后未上传的计算，不能承诺无限时长或无损续训半个 fit。
- **准确恢复**：Owner 在同一 shard 的新会话，从明确指定且已验证 SHA
  的 ZIP 使用现有 `restore-archive`，并附 `--resume`；未完成 trial
  可能重算，但已有完整 trial 不重算。不得自动挑选一个目录下最新 ZIP。
- **独立归并门禁**：以唯一 `trial_id` 去重，校验所有分片原始 plan、
  SHA、研究来源、每个 fold/candidate/seed 的完成回执；缺失或重复
  trial = BLOCKED，不允许做胜者排名。当前本 PR **尚未提供最终合并器
  或真实长会话 Run All Notebook**，这些是下一个执行切片。
- **时间窗口**：Colab 运行时存在动态限制。一般上限约12小时，
  Pro+ 在条件满足时可连续最多24小时；多个标签页不保证多个独立 VM。
  免费环境无正 CU 时不得将交互 Notebook 变成受限的 distributed workers；
  禁止多账号绕过 Colab 额度。
  官方政策 https://research.google.com/colaboratory/faq.html
  https://colab.research.google.com/notebooks/pro.ipynb
- **成本纪律**：先运行单个分片确保数值/保存/恢复，再试第二个独立窗口；
  任务真正不同、资格允许且资源足够时可并行。没有完成的云资源/许可/容量
  认证必须保持 NOT_TESTED，不拿多窗口数量充当独立样本量。

### 本地 Agent 的最小后续任务（不创建多余调度架构）

1. 对 **已有可执行** E2 spec 跑 `create / verify` + 三分片 CLI 测试，
   输出分片 trial ID 全覆盖和互斥证据；对1个可执行小批次手工做
   Colab A 单窗口**真实**训练 → ZIP → 断线恢复 → 核对归档。
2. 针对同一 frozen spec 制作两个独立 Run All Notebook，
   各自固定 s01/s02，强制本分片 Drive 输出路径，自动 chunk/checkpoint，
   成功/阻塞原因清晰打印，无需让 Owner 改参数。
3. 本地审核程序应验证分片合并的 **full coverage、no duplicates、
   per-trial receipt identity、numerical consistency**，并将
   `incoming_unreviewed` 转交独立 Reviewer；不得覆盖原始分片包。
4. C1 新模型和特征适配器独立完成后再下发大计算，首次候选评估只能
   `RETROSPECTIVE_ALREADY_CONSUMED`；E7 前瞻时间序列另行累积。
5. 与 Launch lane 脱钩；本 PR 不是产品 Beta / v1 的发布阻断项。

验收：manifest 与 E2 过滤器单元测试 PASS；1窗口真实分片断点恢复 PASS；
2窗口隔离、不覆盖、同源完整归并 PASS 后，才称为
**MULTI_NOTEBOOK_LONG_CAMPAIGN_READY**。本次代码自身只主张
**SHARD_ASSIGNMENT_IMPLEMENTED, CLOUD_LONG_RUN_NOT_TESTED**。
