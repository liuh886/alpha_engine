# Gate A2 数据可信性与依赖清单核准审计报告 (Data Integrity Audit)

- **审计基准**: `main` @ `f97d8b5507` (2026-11-01)
- **归属事项**: Gate A2 / Issue [#324](https://github.com/liuh886/alpha_engine/issues/324) / Issue [#325](https://github.com/liuh886/alpha_engine/issues/325) / Issue [#1279](https://github.com/liuh886/alpha_engine/pull/1279)
- **门禁裁决**: **四策略运行数据面 PASS**；**实验性全量研究训练数据面 SCOPED_BLOCKED**；整体 Gate A2 按 Fail-closed 规范维持 **BLOCKED**（杜绝虚标全部通过）。
- **核心铁律**: `research_only=true`, `trade_ready=false`。

---

## 1. 四策略运行数据面依赖核准

根据权威注册表 [`configs/strategies/registry.json`](file:///D:/Documents/GitHub/alphaengine/configs/strategies/registry.json)，控制台维护的四策略运行数据流与底层实验性全量训练数据面（US87/CN130 Alpha158 与 PIT 基本面）已实现**完全物理与逻辑解耦**。

| 策略标识 | 模型版本 | 契约路径 | 数据来源与供应商 | 复权与价格基准 | 调仓与观测周期 | 状态核准 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `qqq_rotation` | `qqqi_qqq_tqqq_v4_3` | `configs/research_paradigms/qqqi_qqq_tqqq_current_baseline.yaml` | Yahoo Finance (`yahoo_research_v2`) + CNN 恐贪 | `governed_adjusted_open` (`uniform_adj_close_ratio`)，单边 10 bps 摩擦 | 美股每日收盘评估，次日开盘生效 | **PASS** (已验证) |
| `us_x` | `us_x1_3` | `configs/models/us_x1_3.yaml` | pyqlib 二进制数据池 (`data/providers/us`) | `governed_adjusted_close`，单边 20 bps 摩擦 | 每 10 个提供商交易日重平衡，盘中 Provisional MTM | **PASS** (已验证) |
| `cn_27` | `cn_27_v1_3` | `configs/models/cn_27_v1_3.yaml` | pyqlib 二进制数据池 (`data/providers/cn`) + 腾讯前复权恢复适配器 | `governed_front_adjusted_open` (QFQ)，股票 5/10 bps，ETF 2/2 bps | 每 30 个 A 股交易日重平衡，锁定目标逐日重试 | **PASS** (已验证) |
| `byd` | `byd_v1_3_recovery_event_low_vol_confirmation_v1` | `configs/models/byd_v1_3_recovery_event_low_vol_confirmation_v1.yaml` | 历史封存快照 + 前瞻影子账本（Yahoo/AkShare/新浪交叉对账） | `governed_adjusted_common_open` (乘法链式复权) | A 股每日收盘评估，双标的共同交易日执行 | **PASS** (已验证) |

### 关键结论
- 四策略无一在运行时直接发起未授权的商业数据源拉取或无凭据的 API 调用；
- 运行时无未来函数（无前瞻填充、无无公告的标的替换、无未经复权的价格混用）；
- 窄策略（Narrow Strategy）依赖已全部闭环，不受 US87/CN130 宽表训练缺口的影响。

---

## 2. Gate A2 契约与负面测试验证矩阵

针对数据可信性、复权机制、VWAP 守恒与 PIT 边界，执行了全量契约与负面测试套件，**56 项测试 100% 绿灯通过（耗时 6.61s）**：

| 测试套件 | 用例数 | 状态 | 核心验证不变量 |
| :--- | :---: | :---: | :--- |
| `tests/test_canonical_vwap.py` | 12 | **PASS** | 严格断言成交额转入复权价格基准；拦截任何人工合成 VWAP；断言成交量未调整与复权后必须完全一致；交易日历严格对齐；包络线违规严苛拦截（$\le 0.5$ 美分）；OTC 标的显式策略覆盖。 |
| `tests/test_alpaca_adapter.py` | 10 | **PASS** | 验证 SIP 逐日行情分页拉取与复权归一化；显式 OTC feed 声明校验；标的身份篡改与缺少 VWAP 强制拦截；严格隐蔽凭据，HTTP 错误日志绝无 API Key 明文暴露。 |
| `tests/test_selected_pool_event_population.py` | 14 | **PASS** | 东方财富空分红数据（`code 9201`）安全空帧解析，未知异常 Fail-closed；新浪财报必须与巨潮资讯（CNINFO）披露时间完成时点 Join；SEC 映射 CIK 零填充与 User Agent 默认回退。 |
| `tests/test_cn_selected_pool_event_sources.py` | 5 | **PASS** | 标的间严格单线程串行（防封 IP），标的内 3 供应商并发流水线；精确截止日快照无网络复用；旧版缓存平滑迁移。 |
| `tests/test_ashare_primary_company_events.py` | 9 | **PASS** | 回购公告标题五阶段精准分类；剔除股权激励注销；解禁公告仅保留实质上市流通事件；严格优先读取完整公告正文。 |
| `tests/test_fundamental_event_store_contract.py` | 6 | **PASS** | 确定性 64 位 SHA-256 `event_id`；严厉拦截 `available_at < reported_at`（前瞻未来数据时序倒置）；禁止事实源中隐瞒衍生规则。 |

---

## 3. 外部源权限与凭据预检 (Issue #324 / #325)

依据最新远端与本地环境审计，核实外部数据源配置状态：

### 3.1 Alpaca API 与美股 87 池行情 (Issue #325)
- **配置名称**: `APCA_API_KEY_ID` 与 `APCA_API_SECRET_KEY` 已在远端 GitHub Secrets 注册；
- **SIP 权限**: 覆盖 US87 中 85 只主流标的（`AAPL`, `MSFT`, `NVDA` 等），经回测流水线验证可用；
- **OTC 权限受限**: 针对 `ABBNY` 与 `SBGSY` 两只场外 ADR，Alpaca 返回 `HTTP 403 Forbidden`（需开通机构经纪商计划）。近期研究切片已在 `alpha158_us87_recent_research_v1.yaml` 中配置 Polygon 作为备选，但在全量历史严格契约下保持 **SCOPED_BLOCKED**。
- **影响范围**: 仅影响全量 US87 Alpha158 训练宽表生成；**对当前四策略控制台零影响**。

### 3.2 SEC Company Facts 与代理合规 (Issue #324)
- **User Agent**: `resolve_sec_user_agent()` 已实现安全回退机制（默认 `AlphaEngine Research research@alphaengine.org`），无需单独环境变量即可合规请求；速率限制严格硬编码为每秒最多 8.3 次请求（低于 SEC 10 次/秒上限）；
- **Egress Proxy**: 默认 `SEC_EGRESS_MODE="direct"`，未声明外部代理，遵循直接 HTTPS 白名单（`data.sec.gov`, `www.sec.gov`）；
- **标的缺口**: `SBGSY` 无 SEC CIK，已在 `us_selected_equities_sec_cik_v3.yaml` 冻结为 `identity_missing` 声明，保持候选池成员但阻止缺失事实；
- **影响范围**: 仅影响 US87 基本面事件宽表；**对当前四策略控制台零影响**。

### 3.3 CN130 事件数据源
- 新浪财报 + 巨潮公告时间戳时点 Join 正常运作；
- 新上市标的 `301666`（爱迪特）因上市时间较短，历史基本面数据天然短缺，已被正确标记并记录局限；
- **影响范围**: 仅影响 CN130 基本面事件宽表；**对当前四策略控制台零影响**。

---

## 4. 门禁裁定与后续动作

1. **Gate A2 状态认定**:
   - **四策略运营数据完整性 (Operational Data Plane)**: **PASS**。四策略所需数据切片、复权口径、调仓会话与执行边界均已精确对账且全量绿灯；
   - **全量模型训练数据面 (Training Data Plane)**: 维持 **SCOPED_BLOCKED**（受限于 OTC 数据源权限与新标的历史长度）；
   - **总体 Gate A2**: 依据真实谨慎原则，记为 **BLOCKED (Operations PASS / Research Training SCOPED_BLOCKED)**。
2. **消除了过时的错误声称**:
   - 纠正了“尚未配置 Alpaca 凭据”的陈旧描述；
   - 澄清了 SEC User Agent 具备内置合规回退，不需要单独设置代理即可工作；
   - 证明了四策略控制台上线的独立性，不受实验性训练数据面阻塞的外溢影响。
3. **下一步执行计划**:
   - 推进到 **Gate A4 安全与权限验收 (#1279 / #1288)**，核验公开历史披露处置与当前运行权限控制；
   - 推进到 **Gate A6 发布与恢复演练 (#1281)**。
