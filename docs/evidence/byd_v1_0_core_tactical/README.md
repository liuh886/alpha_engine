# BYD V1.0 core/tactical evidence

## Decision

- Decision: `byd_v1_0_core_tactical_supported`
- Selected rule: `core75_regime_mom_120`
- Status: `research_only=true`, `trade_ready=false`
- Prospective confirmation required: `true`
- Evidence cutoff: `2026-08-03`
- GitHub Actions run: `30877891328`
- Evidence artifact: `8880201424`
- Artifact ZIP SHA-256: `089a46e3b321ac79f80f73a78feaadbd7f1b4741d98b21a82fbff623f80a2c92`

The preceding binary `BYD / CASH` screen returned `byd_v1_0_not_supported`. BYD V1.0 therefore uses a permanent 75% core position and a 25% tactical sleeve rather than attempting to move the whole portfolio in and out of BYD.

## Frozen rule

At each session close:

- switch the tactical sleeve on when close is above SMA120 and 20-session momentum is positive;
- switch the tactical sleeve off when close is below SMA120 and 60-session momentum is negative;
- target 100% BYD when the tactical sleeve is on;
- target 75% BYD and 25% cash when the tactical sleeve is off;
- execute the target at the next session open.

The asymmetric entry/exit conditions add hysteresis and keep the strategy in BYD through ordinary pullbacks. No shorting, leverage, intraday execution or same-close execution is permitted.

## Data identity

- Instrument: BYD A share `002594.SZ`
- Provider accepted by the frozen ladder: `yfinance_auto_adjusted`
- Adjustment: `auto_adjust=true`, `repair=true`
- Rows: `3,663`
- Range: `2011-06-30` to `2026-08-03`
- OHLCV SHA-256: `84365ce1549b8a598fbf965c5033f61f80a30decf14b316061c0af218d7f1234`
- Primary cost: 20 bps per unit of position change
- Stress cost: 40 bps per unit of position change

BaoStock and AkShare/Eastmoney were attempted first but failed on the hosted runner. The accepted history is entirely from Yahoo; no provider stitching was used.

## Selection evidence: 2012–2024

| Metric | BYD V1.0 | Buy and hold | Read-through |
| --- | ---: | ---: | --- |
| Total return | 1,051.59% | 1,155.12% | Retains most secular upside |
| CAGR | 21.55% | 22.39% | 96.25% CAGR retention |
| Max drawdown | -53.69% | -56.22% | Improves 2.53 percentage points |
| Calmar | 0.4015 | 0.3983 | Slightly higher |
| Sortino | 1.0234 | 1.0135 | Slightly higher |
| Average BYD exposure | 89.33% | 100.00% | Tactical sleeve is deliberately small |
| Round-trip equivalents/year | 0.65 | 0.00 | Low-frequency execution |

At 40 bps cost, the selected rule still produced a positive 2012–2024 total return of 1,014.91%. The largest positive defense episode contributed 46.99% of total positive defense contribution, below the frozen 50% concentration cap.

## Fixed validation: 2023–2024

| Metric | BYD V1.0 | Buy and hold | Read-through |
| --- | ---: | ---: | --- |
| Total return | 12.05% | 12.22% | Nearly identical terminal return |
| CAGR | 6.10% | 6.19% | Only 0.08 percentage-point shortfall |
| Max drawdown | -41.39% | -45.82% | Improves 4.43 percentage points |
| Calmar | 0.1475 | 0.1350 | Higher |

This is the key distinction from the rejected binary candidates: the core/tactical rule did not sacrifice the validation-period return merely to lower exposure.

## Retrospective holdout: 2025–2026-08-03

This window is explicitly classified as a `retrospective_holdout`, not prospective evidence.

| Metric | BYD V1.0 | Buy and hold | Read-through |
| --- | ---: | ---: | --- |
| Total return | 6.83% | 3.40% | Higher by 3.43 percentage points |
| CAGR | 4.45% | 2.23% | Higher |
| Max drawdown | -37.83% | -42.94% | Improves 5.11 percentage points |
| Calmar | 0.1178 | 0.0519 | More than twice the reference |
| 40 bps total return | 6.51% | — | Remains positive |

All frozen retrospective-holdout gates passed. This does not make the model trade-ready because the phase-two holdout was evaluated during the same research work session.

## Latest governed state

- Position executed at the last measurable open-to-open row: `100% BYD`
- Target generated after the `2026-08-03` close for the next open: `75% BYD / 25% cash`

This state is evidence output, not an order or personal investment recommendation.

## Promotion boundary

BYD V1.0 may enter prospective shadow monitoring with the rule and thresholds unchanged. Promotion beyond research requires independently accumulated forward signals, observed execution timing, provider continuity and evidence that the 75%/100% state changes remain useful after costs.
