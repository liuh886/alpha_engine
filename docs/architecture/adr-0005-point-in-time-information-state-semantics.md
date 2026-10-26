# ADR-0005: Point-In-Time (PIT) Information-State Semantics & Negative Boundaries (RI-02)

- **Status**: **DRAFT / ARCHITECTURE DISCUSSION PROPOSAL (Track B / PR #1296)**
- **Context Date**: 2026-10-26 (Revised 2026-10-27)
- **Deciders**: Personal Quant Workstation Owner & Architecture Agent
- **Relationship to Prior ADRs**: **Subordinate to ADR-0003** (Extends research data-plane semantics under ADR-0003; does NOT supersede product boundaries or create a dual registry/state system)

---

## 1. Context & Problem Statement

Quantitative research across distinct asset classes and markets (US Equities, CN Equities, Reference ETFs) frequently encounters subtle lookahead bias and hindsight data corruption:
1. **Filing Lag vs Event Period**: A company's fiscal quarter ends on September 30, but the official filing occurs on November 10. Using Q3 data on October 15 is a severe lookahead violation.
2. **Post-Cutoff Restatements**: Financial statements and dividend records are sometimes retroactively restated months or years later. Backtesting against restated data incorporates information that was impossible to know at execution time.
3. **Unverifiable Ingestion Timestamps**: Historical vendor feeds queried today ($t_{retrieved} = \text{today}$) report an "effective date", but cannot prove that the data was machine-readable in production on that historical date. Assuming that historical vendor data was instantly available at release time introduces insidious lookahead bias.
4. **Adjustment Flips & Price Drift**: Splitting or paying dividends alters historical adjusted prices. Mixing raw prices with post-split adjustments creates false arbitrage or misleading factor values.

Alpha Engine requires an authoritative, model-agnostic definition of **Information State at Cutoff $T$** (`as-of $T$`), compatible with ADR-0003 product boundaries.

---

## 2. Decision: The Five-Timestamp Model & Evidence Hierarchy

### 2.1 Five Canonical Timestamps
For any observation $O$ evaluated at cutoff $T$, the system distinguishes five canonical timestamps:

1. **$t_{event}$ (Event Time)**: The period or physical occurrence date (e.g., fiscal quarter end date `2026-09-30`, trading session date `2026-10-23`).
2. **$t_{release}$ (Public Release Time)**: The timestamp when the information became publicly disseminated (e.g., SEC EDGAR filing timestamp, exchange announcement date).
3. **$t_{available}$ (Machine-Readable Ingestion Time)**: The timestamp when the data was verified and ingested into a machine-readable data store.
4. **$t_{retrieved}$ (Workstation Query Time)**: The actual wall-clock execution time when Alpha Engine retrieved and sealed the observation into local evidence.
5. **$t_{revision}$ (Revision Timestamp)**: The timestamp of any subsequent amendment or restatement by the issuer or vendor.

### 2.2 Timestamp Evidence Grades (证据等级)
Because vendor $t_{available}$ is often unverifiable in historical replay, timestamps are classified into three strict evidence grades:

| Grade | Classification | Source / Proof Requirement | Engine Ingestion Policy |
| :--- | :--- | :--- | :--- |
| **Grade 1 (Official / Cryptographic)** | SEC EDGAR dissemination timestamp, Exchange circular timestamp with official log. | High confidence: $\max(t_{release}, t_{available}) \le T$ verifiable. | Accepted if $t_{release} \le T$ and filed before market close, or $T \ge t_{release} + 1 \text{ session}$ if after close. |
| **Grade 2 (Audited Vendor Snapshot)** | Contemporaneous, immutable snapshot manifest captured and sealed on date $T$ (e.g., daily shadow store). | Verified machine-readable on $T$: $t_{retrieved} \le T$. | Accepted up to the exact sealed cutoff $T$. |
| **Grade 3 (Post-Hoc Retrieved / Unverified)** | Data retrieved today ($t_{retrieved} > T$) without historical ingestion logs. | Unverifiable historical availability: retrieval today does **not** prove availability at $T$. | **Conservative Fallback**: Must enforce conservative market session lag (minimum $+1$ trading session after confirmed $t_{release}$); if $t_{release}$ cannot be proven $\le T$, fail closed (`data_blocked`). |

### 2.3 The Cardinal PIT Constraints
1. **Availability Constraint**:
   An observation $O$ is eligible for strategy evaluation at cutoff $T$ if and only if its proven evidence satisfies:
   $$\max(t_{release}, t_{available}) \le T \quad (\text{with Grade 3 conservative lag enforced})$$
2. **Restatement Isolation**:
   If a restatement occurs at $t_{revision} > T$, the restated value is **strictly forbidden** in historical evaluation as of $T$. The evaluation must utilize only the value known and available at $T$.

---

## 3. Data Representation Rules

### 3.1 Raw Prices vs Adjusted Bases
- **Raw OHLCV**: Always preserved immutably as reported by the exchange.
- **Adjustment Factors**: Versioned explicitly with corporate action effective dates (`ex_date`).
- **Chain-Linked Series**: When continuous adjusted bars are materialized, the adjustment base anchor date must be explicitly declared. Never mix adjustment bases across different cutoff dates without an explicit bridge.

### 3.2 Missing Values vs Zero
- Missing financial statement items or unavailable trading bars must be represented as **`NaN` / `missing`**, never coerced to zero.
- Coercing missing data to zero falsifies factor values (e.g., R&D expense, debt ratios, volume).
- Where required inputs are missing at cutoff $T$, the strategy state must become `data_blocked`, not forward-filled.

### 3.3 Volume Governance across Fallback Vendors
- Volume availability is governed separately from price availability.
- Overlap historical data ($t \le T_{cutoff}$) must strictly retain the original verified values.
- Extension data from fallback vendors must be standardized to governed unit scales (shares vs lots). If the volume scale cannot be verified, volume-dependent factor calculation must be blocked rather than silently accepting corrupted units.

---

## 4. Negative Test Matrix & Assertions (Negative Verification)

Every PIT data adapter and query interface must pass the following negative assertions:

| Test Case ID | Failure Injection | Expected Engine Behavior | Severity |
| :--- | :--- | :--- | :--- |
| **PIT-NEG-01** | Query Q3 fundamental data with cutoff $T < t_{release}$ | Raise `LookaheadViolationError` or return `None` (fail-closed) | **P0 (Critical)** |
| **PIT-NEG-02** | Supply a post-cutoff restatement where $t_{revision} > T$ | Ignore revision; retain original verified snapshot at $T$ | **P0 (Critical)** |
| **PIT-NEG-03** | Request candidate trading on an unlisted or delisted session | Raise `NonTradableSessionError`; exclude from active weights | **P1 (High)** |
| **PIT-NEG-04** | Attempt to join unaligned US and CN calendar sessions | Raise `CalendarMismatchError` without explicit cross-market bridge | **P1 (High)** |
| **PIT-NEG-05** | Fallback vendor provides unverified volume scaling (arbitrary ratio) | Raise `cutoff fallback differs from governed overlap` (`mismatched_fields=volume`); block volume-dependent research | **P0 (Critical)** |
| **PIT-NEG-06** | Grade 3 unverified vendor ingestion timestamp without conservative lag proof | Fail-closed (`data_blocked`); reject unproven historical availability | **P1 (High)** |

---

## 5. Consequences & Boundaries

- **Single Authority Preserved**: Subordinate to ADR-0003; does not introduce parallel strategy registries, separate state machines, or bypass immutable evidence contracts.
- **Eliminates Lookahead Leakage**: Distinguishes event time from proven machine-readable availability, preventing artificial Sharpe inflation.
- **Fail-Closed Governance**: Data gaps and unverified vendor timelines honestly produce `blocked` / `partial` statuses rather than ungrounded assumptions.
