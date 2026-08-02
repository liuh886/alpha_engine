# QQQI / QQQ / TQQQ v4.2 blended-SGOV episode attribution result

**Evidence date:** 2026-08-02  
**Economic sample:** 2024-01-30 through 2026-07-30  
**Current baseline:** `qqqi_qqq_tqqq_vxn_bridge_v4_2`  
**Challenger:** `qqqi_sgov_blended_defense`  
**Official cost:** 10 basis points per turnover unit  
**Status:** research-only; not trade-ready

## Executive decision

1. Keep v4.2 unchanged as the current research baseline and alert source.
2. Retain the blended QQQI/SGOV structure as a descriptive drawdown-focused allocation profile.
3. Do not create a separate prospective signal monitor for the blended structure yet.
4. Do not search additional SGOV weights.
5. Move the active research program to prospective v4.2 alert and execution evidence.

The blended structure protects the portfolio consistently at major v4.2 troughs, but its recovery penalty is too large for the pre-registered monitor-only gate.

## 1. Frozen structures

### Current v4.2 baseline

- state 0: 100% QQQI;
- state 1: 50% QQQI / 50% QQQ;
- state 2: 25% QQQ / 75% TQQQ.

### Blended defensive profile

- state 0: 50% QQQI / 50% SGOV;
- state 1: 25% QQQI / 25% SGOV / 50% QQQ;
- state 2: unchanged 25% QQQ / 75% TQQQ.

The two strategies use the exact same state trace, next-open execution and 10 bps cost convention. The experiment tests defensive-asset architecture, not signal quality.

## 2. Methodology correction

The first exploratory run measured the challenger's maximum drawdown from the start of a baseline episode until the challenger eventually recovered. If the challenger remained underwater through a later baseline drawdown, the later stress could be counted against the earlier episode and then counted again as its own episode.

That exploratory result was rejected.

The accepted method separates two dimensions:

- **trough protection:** compare both strategies at the same v4.2 baseline trough;
- **recovery cost:** measure how many additional trading sessions the challenger requires to regain its value at the common episode start.

This prevents subsequent drawdowns from being double-counted while preserving the economically important recovery penalty.

## 3. Headline portfolio trade-off

| Strategy | CAGR | Volatility | Sharpe | Sortino | Maximum drawdown | Calmar | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| Current v4.2 | **33.06%** | 25.62% | 1.244 | 1.801 | -24.22% | 1.365 | 55 |
| Blended QQQI/SGOV | 29.54% | **19.75%** | **1.410** | **2.042** | **-17.91%** | **1.649** | 55 |

The blended profile gives up about **3.52 percentage points of CAGR** while materially reducing volatility and drawdown depth. The cost and turnover are unchanged; the difference comes from the defensive sleeve.

## 4. Five largest v4.2 drawdown episodes

| Rank | Episode start | v4.2 trough | v4.2 drawdown | Blended drawdown at same trough | Protection | Recovery lag |
|---:|---|---|---:|---:|---:|---:|
| 1 | 2024-12-16 | 2025-04-04 | -24.22% | -16.03% | **+8.20 pp** | 0 sessions |
| 2 | 2024-07-10 | 2024-09-06 | -16.91% | -14.88% | **+2.03 pp** | 114 sessions |
| 3 | 2026-06-02 | 2026-07-29 | -15.46% | -14.76% | **+0.71 pp** | unresolved |
| 4 | 2026-01-27 | 2026-03-30 | -8.79% | -4.15% | **+4.64 pp** | -4 sessions |
| 5 | 2024-02-01 | 2024-04-19 | -7.60% | -3.23% | **+4.38 pp** | 132 sessions |

### Protection result

- all five major v4.2 troughs improved;
- major-episode improvement rate: **100%**;
- median trough protection: **4.38 percentage points**;
- early major-episode improvement rate: **100%**;
- late major-episode improvement rate: **100%**;
- largest episode supplied about **41.10%** of total positive protection, below the 60% concentration ceiling.

The drawdown protection is therefore real, chronologically consistent and not dependent on only one event.

### Recovery result

The recovery side is materially weaker:

- median recovery lag among resolved major episodes: **57 trading sessions**;
- pre-registered maximum: 30 sessions;
- one major episode remained unresolved at the sample end;
- two historical episodes required 114 and 132 additional sessions;
- only the 2026-01-27 episode recovered earlier than v4.2.

The monitor-only gate fails solely on recovery duration.

## 5. Why the trade-off occurs

Exact log-relative-wealth attribution across the five major episodes shows:

| Phase | State 0 contribution | State 1 contribution | State 2 contribution | Interpretation |
|---|---:|---:|---:|---|
| Peak to v4.2 trough | **+0.2180** | **+0.0131** | 0.0000 | SGOV protects during defensive and bridge periods |
| Trough to v4.2 recovery | **-0.1725** | **-0.0195** | 0.0000 | QQQI participates more strongly in rebound periods |
| After v4.2 recovery until challenger recovery | -0.0077 | -0.0183 | 0.0000 | remaining lag is concentrated outside state 2 |

State 2 contributes exactly zero to the relative result because both structures use the same 25% QQQ / 75% TQQQ allocation.

The economic mechanism is therefore straightforward:

> SGOV reduces loss depth while the model is defensive, but replacing part of QQQI also removes some recovery participation. The portfolio falls less, yet can take longer to regain the prior peak.

## 6. Pre-registered gate

| Check | Threshold | Result | Pass |
|---|---:|---:|---|
| Major-episode improvement rate | ≥60% | 100% | Yes |
| Median trough protection | ≥1.00 pp | 4.38 pp | Yes |
| Median recovery lag | ≤30 sessions | 57 sessions | **No** |
| Early consistency | ≥50% | 100% | Yes |
| Late consistency | ≥50% | 100% | Yes |
| Largest-event concentration | ≤60% | 41.10% | Yes |
| CAGR sacrifice | ≤4.00 pp | 3.52 pp | Yes |

**Decision:** `retain_descriptive_drawdown_profile_only`.

A separate prospective monitor is not authorized because the profile does not yet offer a sufficiently balanced drawdown-and-recovery proposition.

## 7. Implications

### For the current strategy

v4.2 remains the better general-purpose baseline because it retains higher compound growth and substantially faster recovery while keeping the same signal architecture.

### For a drawdown-sensitive user

The blended profile remains useful as an explicitly different risk preference. It should be presented as:

- lower volatility;
- shallower major troughs;
- lower CAGR;
- potentially much longer recovery.

It must not be described as a universally superior model.

### For further SGOV research

No additional SGOV-weight search is allowed on the current sample. The 50/50 structure has already established the mechanism. Further retrospective weights would optimize the trade-off rather than validate it.

## 8. Next active stage

The active program moves to prospective v4.2 operating evidence:

- Telegram and GitHub delivery status;
- data freshness;
- alert fingerprint and deduplication;
- theoretical next-open price;
- observed or paper execution price;
- opening gap, slippage and cost deviation;
- later 5-, 10-, 20- and 40-session outcomes;
- confirmation or reversal of each state change.

No model rule changes are authorized during this collection stage.

## 9. Evidence

- workflow: `QQQI v4.2 SGOV Episode Attribution`;
- workflow run: `30734414386`;
- artifact ID: `8829046855`;
- artifact digest: `sha256:da1d5f7c4b4b36ec21fbeecd6185030b2c7f5be95f8eb15eac21a2854257d55f`;
- notebook: `notebooks/21_qqqi_qqq_tqqq_v4_2_sgov_episode_attribution.ipynb`.

The evidence bundle contains coverage, headline and chronological metrics, every drawdown episode, the five major episodes, phase/state contribution tables, the machine-readable gate result and the executed notebook.
