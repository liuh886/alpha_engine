# Trading Routine Failure Classification & Attribution Template

## 1. Classification Categories

| Category | Code | Description | Examples |
| :--- | :--- | :--- | :--- |
| **Data Source** | `DATA_*` | Issues related to raw data ingestion or quality. | API 429, missing NaNs, stale quotes. |
| **Inference Engine** | `INF_*` | Logic or model-related failures during execution. | Model load error, feature mismatch, OOM. |
| **Risk Veto** | `RISK_*` | Execution blocked by safety guardrails. | High volatility, panic index exceeded, leverage cap. |
| **Infrastructure** | `SYS_*` | System, network, or hardware level issues. | Connection refused, disk full, process crash. |
| **Human/Config** | `CFG_*` | Errors in configuration or manual intervention. | Wrong API key, manual stop, invalid `.env`. |

---

## 2. Attribution & Recoverability

- **Source**: 
  - `INTERNAL`: Bug in code, configuration error, local resource exhaustion.
  - `EXTERNAL`: Upstream API failure, market conditions (Veto), connectivity.
- **Recoverability**:
  - `AUTO`: System can retry after a cooldown.
  - `SEMI`: Requires a human "kick" or simple config tweak.
  - `MANUAL`: Requires code change or infrastructure intervention.

---

## 3. Triage & Review Log (Closed-Loop)

| Timestamp | Category | Attribution | Recoverability | Case Summary & Resolution |
| :--- | :--- | :--- | :--- | :--- |
| 2026-03-01 17:41:06 | `RISK_VETO` | `EXTERNAL` | `AUTO` | Panic index (86.8) triggered safety veto. **Resolution**: System working as intended. **Next**: Monitor index for stabilization. |

---

## 4. Improvement Backlog (from Reviews)

- [ ] **[IMP-001]**: Add `Panic_Recovery` check to automatically resume run if index drops < 50 within the same trading window.
- [ ] **[IMP-002]**: Implement better `ECONNREFUSED` retry logic for Dashboard <-> API connection.
