# US x1.1 Sector, Market-Style and 2025H1 Drawdown Attribution

Date: 2026-08-03  
Issues: #366, #381  
Implementation: PR #430  
Status: research only; `trade_ready=false`

## Decision

`mixed_sector_style_regime`

The taxonomy label is retained exactly as pre-registered. In the observed evidence, the active mechanisms are **sector concentration and market style**; the QQQ-regime gate did **not** pass.

- sector signal: `true`;
- style signal: `true`;
- QQQ-regime signal: `false`;
- automatic model update: `false`;
- creates US x1.2 candidate: `false`.

## Evidence identity

- frozen provider identity: `5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95`;
- source deterministic reproduction artifact: `8831960659`;
- evidence workflow: `30777873616`;
- evidence artifact: `8842672379`;
- artifact digest: `sha256:2f2f9451c092b05d3405a1e5e3f01af4c0a5a479465e937f43809feea14bd0d2`;
- governed candidate classification: 87/87 equities;
- classification standard: `alpha_engine_us_research_sector_v1`;
- classification records SHA-256: `a9493d111de9ab2a6a4cadbb9feb1219ffa33291bd2db1d006124cf7c1747cd2`.

The classification is an Alpha Engine research asset based on issuer primary business. It is not represented as licensed GICS, ICB, TRBC or BICS data. QQQ remains benchmark-only. TIGO is explicitly bound to Millicom International Cellular; TYGO is Tigo Energy.

All four development windows reproduced the deterministic US x1.1 baseline within `1e-6` before any attribution was accepted.

## 2025H1 drawdown path

| Item | Result |
|---|---:|
| Peak | 2025-02-03, NAV 1.1659 |
| Initial shock | 2025-02-18, -21.07% period return |
| Trough | 2025-04-01, NAV 0.7709 |
| Maximum drawdown | -33.88% |
| Recovery within 2025H1 | No |

The drawdown therefore contains an abrupt initial shock followed by a continuation phase. The initial shock occurred before a negative QQQ 20-session trend could fully identify the regime, consistent with Phase A.

## Sector and industry mechanism

During the peak-to-trough interval:

- mean sector HHI: **0.5756**;
- maximum single-sector weight: **86.67%**;
- Technology reached 60.00%, 86.67%, 80.00% and 66.67% across the four drawdown rebalances;
- Technology represented **70.26%** of all negative name-level contribution;
- the leading individual industry was Semiconductors, but it represented only **26.88%** of negative contribution.

### Net arithmetic contribution by sector during drawdown

| Sector | Net contribution |
|---|---:|
| Technology | -25.44 pp |
| Health Care | -5.19 pp |
| Industrials | -3.97 pp |
| Financials | -2.12 pp |
| Consumer Discretionary | -1.52 pp |
| Communication Services | +0.18 pp |

Technology was the dominant sector-level loss source, but the loss was broad within Technology. Major negative industries included Semiconductors, application software and digital advertising, health-care technology, health-care services, capital markets, AI/cloud infrastructure, data-center infrastructure, electrical equipment and construction engineering.

The largest negative names remained APP, HIMX, TEM, HIMS, PLTR, HOOD, NBIS, IREN, INTC and BE. The distribution across many names and industries confirms that this was not a single-name failure.

## Market-style mechanism

Only point-in-time, market-derived styles were used. Every signal-date snapshot used completed observations before the rebalance date.

| Style dimension | Dominant negative bucket | Negative-loss share |
|---|---|---:|
| 60-session volatility | High volatility | 87.98% |
| 60-session QQQ beta | High beta | 83.73% |
| 60-session momentum | Leader | 48.36% |
| 20-session liquidity | High liquidity | 43.37% |
| 20-session momentum | Laggard | 40.35% |

The result is a clear high-volatility and high-beta exposure mechanism. Momentum and liquidity do not identify one comparably dominant bucket.

Style coverage was approximately 94%–100% across the four development windows. No value, growth, quality or fundamental-size claim is made because governed point-in-time fundamentals were not used in this phase.

This finding uses 60-session, fixed-US87 cross-sectional buckets and therefore does not contradict Phase A mechanically. Phase A used a different short-window selected-name diagnostic. Phase B is the governed mechanism result for this style definition.

## QQQ regime

Negative QQQ-trend periods represented **52.72%** of negative contribution. This is economically relevant but below the pre-registered 60% regime-dominance threshold.

The 2025H1 drawdown is therefore not adequately described as a pure benchmark-regime event. Sector concentration and high-beta/high-volatility selection are the stronger mechanisms.

## Brinson-style decomposition

Against an equal-weight fixed-US87 internal reference, full-window 2025H1 effects were:

| Sector | Allocation | Within-sector selection | Interaction | Total |
|---|---:|---:|---:|---:|
| Technology | -1.72 pp | -6.60 pp | -0.33 pp | -8.65 pp |
| Industrials | -0.61 pp | -2.78 pp | +0.91 pp | -2.48 pp |
| Consumer Discretionary | -0.61 pp | -1.10 pp | -0.17 pp | -1.89 pp |
| Health Care | -0.18 pp | +7.15 pp | +3.47 pp | +10.43 pp |

Technology's drag arose primarily from **within-sector selection**, with an additional but smaller overweight-allocation penalty. This matters: sector concentration amplified the damage, but merely relabeling the portfolio as “technology-heavy” does not fully explain the loss.

## Counterfactual diagnostics

### Leave one sector out

Excluding Technology from the score cross-section improved 2025H1 maximum drawdown by **12.90 percentage points**, from -33.88% to -20.98%, and increased simple excess by 32.03 percentage points. No other sector produced more than a 1.86-point drawdown improvement.

This is a mechanism diagnostic, not an investable recommendation. Removing an entire sector changes the opportunity set too materially to be adopted as a baseline contract.

### Rank-aware sector cap

The corrected sector-cap diagnostic preserves the Top-15 equal-weight structure. It walks the model ranking in order and admits the next eligible name when a sector has already filled four of the fifteen slots. The effective maximum sector weight is therefore 4/15, or 26.67%, under the pre-registered 30% ceiling.

| Window | Baseline excess | Capped excess, 20 bps | Baseline max DD | Capped max DD |
|---|---:|---:|---:|---:|
| 2024H1 | +11.75% | +27.74% | -6.87% | -4.53% |
| 2024H2 | +32.37% | +26.28% | -13.97% | -11.37% |
| 2025H1 | +5.54% | +32.37% | -33.88% | -29.36% |
| 2025H2 | +47.19% | +11.97% | -19.38% | -26.07% |

Compounded across the four development windows:

| Contract | Strategy return | Relative excess vs QQQ | Worst window DD |
|---|---:|---:|---:|
| US x1.1 baseline, 20 bps | +231.11% | +113.35% | -33.88% |
| Rank-aware sector cap, 20 bps | +242.76% | +120.85% | -29.36% |
| Rank-aware sector cap, 40 bps | +227.98% | +111.33% | -29.65% |
| Rank-aware sector cap, 60 bps | +213.82% | +102.21% | -29.93% |

All four windows retained positive simple excess under the rank-aware cap. The diagnostic reduced the worst-window drawdown by 4.52 percentage points at 20 bps and remained positive under 60 bps.

However, 2025H2 performance deteriorated materially and the evidence comes from the same consumed development windows. The result supports a **separate, pre-registered portfolio-control experiment**; it does not justify silently changing US x1.1 or creating US x1.2 in this PR.

## Conclusion

The most defensible mechanism statement is:

> The 2025H1 US x1.1 drawdown was a broad high-beta and high-volatility technology-selection shock, amplified by extreme sector concentration. It was not dominated by one company, one narrow industry or the QQQ trend regime alone.

US x1.1 remains unchanged. The next bounded research path is a rank-aware sector-cap challenger using the fixed US87 pool, unchanged model scores, the same Top-15 equal-weight contract, 20/40/60 bps cost stress and explicit drawdown/alpha-retention gates. A future untouched challenge window remains mandatory before any operational or release claim.
