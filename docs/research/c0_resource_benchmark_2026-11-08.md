# C0 资源效率垂直切片与下一轮研究准备

**本地 R1/R2 数值一致 PASS；资源扩展 PARTIAL；真实 Colab/GPU/CU NOT_TESTED。**
父 Issue [#1373](https://github.com/liuh886/alpha_engine/issues/1373#issuecomment-6719226869)。
来源 main `1463156c4ad22757d10413a34ef91ca83266e830`；计算代码冻结于
`f7221d5c380f9dd9507540b65bdf4e4133392bcd`，后续文档/Notebook提交不是重算来源。

Owner 已于 2026-11-08 明确：内部自用，取消本项目对供应商证明文件的审查，
按 Owner 授权处理私人 Drive/Colab 研究数据。新合同记录
`owner_internal_research_authorized=true / vendor_document_review_required=false`；
旧许可回执/云标志保持历史原字节，不将 Owner 授权描述为供应商书面认证。

## 计算与数据身份

- [冻结 C0 spec](../../configs/research_experiments/c0_us73_resources_20261108_v3.json)：
  6 个逻辑任务，2 个已消费历史折 × 3 个小 XGB 深度配置，20 rounds、固定 seed67431。
  跨资源 arm 重复是数值/资源配对，不是 HPO 或独立金融样本；上限36次fit。
- [独立数据配置身份](../../configs/research_experiments/c0_dataset_20261108_v3.json)：
  US73 显式子集 + 单列 QQQ；底层复用修复后的 v6 US 行情 ZIP，截止2026-11-03，
  SHA256 `b4745e46fc26b0328e22de50e579ebbf1d400996258ea6ebb43c1ff739ed5a1a`，
  原 manifest SHA256 `4f8225f3c68ee0886b9b707ca140e91dcb509b739b8548fdc10f258574d3da1a`。
  没有改价、刷新供应商、删股、合成 VWAP 或宣称静态池/PIT合格。
- 训练/验证窗口为2024–2025，明确 `RETROSPECTIVE_ALREADY_CONSUMED`；没有新 holdout。
  C0沿用既有Study Workspace执行假设以测资源，不把它冒充下一日策略优化结论。
- 新输出独立存放 `D:/Documents/AlphaEnginePrivate/Launch-Research/2026-11-08/research/local-benchmark-v3`。
  原E4 288、v6 261、E5、E6、E7归档哈希和E7专用运行源码重新核对未变。

复用 `run_study`、canonical XGB native trainer、R1 memory cache、现有模拟器。
C0仅在进程内观察真实fit时间、完整评分和原模拟器返回/权重，保存模型UBJ与NPZ；
没有第二套回测引擎。CPU每worker native thread=1，源码/锁/实际软件与硬件身份进入回执。
训练器的CUDA配置遵循 [XGBoost官方接口](https://xgboost.readthedocs.io/en/stable/gpu/index.html)，
并检查实际模型设备；CPU fallback不能算GPU成功。

## 已执行结果：单次本机先导，不外推 Colab 加速比

| 阶段 | 实际fit | 每任务wall合计（秒） | fit核心合计（秒） | 缓存hit/miss |
| --- | ---: | ---: | ---: | ---: |
| 关闭缓存 | 6 | 56.6714 | 1.7415 | 缓存未启用 |
| 空缓存作用域首遍 | 6 | 27.4338 | 1.9937 | 20 / 10 |
| 同作用域热缓存 | 6 | 11.0920 | 1.6705 | 30 / 0 |

18组完整评分、每日毛/净收益、基准、换手与模拟持仓数组逐元素一致，最大绝对误差0。
表中首遍已有后续任务命中，不把全部6个任务都称冷缓存。热缓存仅指R1内存缓存；未清OS缓存。
R1阶段端到端58.5827秒/采样进程树峰值323.55MiB；R2含两遍12fit，端到端40.7259秒/
334.70MiB。二者任务数不同，不能用这两个wall直接推导加速比。
明显改善来自重复读源/特征处理，不能宣称XGB训练核心加速5倍。

R1完成后退出，再用同身份命令续跑R2；R1 stage SHA未变，没有重复计算其6fit。
每阶段文件按SHA独立读取，硬件/环境变化拒绝拼接；阶段中途失败保留，不能覆盖旧目录。
最终记录18fit、0新增独立金融样本。早期v1配置验证失败（未fit）与v2先导结果也保留，
不混入v3指标。8个定向测试、Ruff与mypy通过。

CPU2/4受本机可用RAM约0.53GiB阻断，冻结保守需求分别约1.63/2.26GiB，
没有放宽预算或假装测得并行收益。容量不足只阻断该CPU arm，不阻断独立的可支持CUDA测量。
当前未请求CUDA，本机无已验证CUDA测量；GPU显存峰值也未测。
RSS是20ms采样进程树内存，非OS严格高水位、非GPU显存。CU未从时间估算。

## 可复现命令与 Notebook

新fit须先checkout精确计算SHA `f7221d5c380f9dd9507540b65bdf4e4133392bcd`，
按原uv.lock创建环境；不能直接在文档已前进的工作分支冒充该计算版本。
已封存结果的独立读取不训练，可在当前分支执行：

```powershell
uv run --frozen python -m src.research.c0_resource_benchmark verify --output D:/Documents/AlphaEnginePrivate/Launch-Research/2026-11-08/research/local-benchmark-v3
```

实际冻结版本执行顺序为：

```text
python -m src.research.c0_resource_benchmark run --spec <c0-spec-v3.json> --data-root <source-stage> --output <new-run> --stop-after r1
python -m src.research.c0_resource_benchmark run --spec <same-spec> --data-root <same-source> --output <same-run>
```

[C0_resource_benchmark.ipynb](../../notebooks/C0_resource_benchmark.ipynb) 已通过格式/每个code cell AST
校验，并在本地只读模式逐单元执行，独立核验实际v3结果，新增fit为0。
这是本地Notebook执行，不是Colab实机验收；首次mount/bootstrap/CUDA/CU/UI输入/真实中断均NOT_TESTED。
Colab配置由Owner手工运行，遵守[官方交互与资源边界](https://research.google.com/colaboratory/faq.html)，
没有外部worker、远控、常驻云服务或调度。

Drive根目录入口为 `AlphaEngine/C0_resource_benchmark.ipynb`；任务文件放在
`AlphaEngine/03_Data/Research_Exchange_P2/colab_jobs/c0-us73-resources-20261108-v3`。
新结果逐阶段保存到该项目 `incoming_unreviewed` 的独立session目录，打印ZIP SHA并回读CRC。
按确切ZIP路径和SHA恢复，不自动选latest；若运行时硬件更换，新建run，保留旧检查点。
CU记录Owner实际UI余额及采集方法，包含安装/暂存，初次Drive挂载前消耗不计；缺读数标NOT_MEASURED。
结果审核须本地重新计算全部索引SHA与数组/环境/实际设备，并保留所有阻断。

## C1预编制与停止条件

[C1队列](../../configs/research_experiments/c1_us73_research_queue_20261108_v1.json) 明确12候选×
最早两个按时间排序的E4折，最多24配置折；不是可执行batch、未运行。
两动量控制复用既有评分；Ridge/ElasticNet、新特征/标签合同仍需实现审查。
预先约束次日收盘参考、统一周频/min5/buffer10、8/25/50bps、同折60/120日动量比较、
1d/5d Rank IC、换手/集中度/贡献和成本break-even。成本重定价不重新fit。
全部2023–26窗口仍retrospective；pilot条件未过即停止，不换窗口/参数美化。
扩至最多192配置折需要独立Owner审查；C0真实云计量未审核前不启动重研究。

回滚：停止C0单次进程，保留各版本结果/检查点，撤销C0功能提交即可。
不触碰E7每日任务、任何生产数据库/权限或E4–E7封存数据。
验收元数据见 [acceptance.json](../evidence/c0_resources_2026-11-08/acceptance.json)。
