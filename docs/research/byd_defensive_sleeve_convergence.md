# BYD defensive-sleeve convergence

Issue: #546  
Status: completed historical convergence; research only  
Decision: retain `515180.SH` as the only ETF in prospective BYD sleeve evidence

## Research boundary

The experiment did not change canonical BYD V1.0. The BYD allocation remained:

- risk-on close target: 100% BYD;
- defensive close target: 75% BYD;
- the released 25% was the only allocation under study.

The universe was frozen before candidate data or performance was read:

- cash;
- `515180.SH`, the retained dividend reference;
- `512890.SH`, the low-volatility dividend challenger;
- `511010.SH`, the five-year government-bond challenger.

No fifth asset, recovery overlay, binary rotation, dynamic sleeve selection, or BYD threshold search was allowed.

## Data decision

### 512890.SH: data blocked

`512890.SH` did not enter performance evaluation. The primary provider row for 2024-03-29 reported:

- open: 0.998000025749;
- high: 1.011000037193;
- close: 1.014999985695;
- required high correction: 0.003999948502;
- violation: 0.3940836% of close.

The frozen envelope-repair ceiling was 0.2%. The candidate was therefore blocked rather than repaired, stitched, or replaced by another provider. The provider reference, audit row, and blocker receipt are sealed in the exact evidence artifact.

### 511010.SH: canonical pass

The sealed `511010.SH` bundle passed every data gate:

- range: 2013-03-05 to 2026-08-03;
- rows: 3,248;
- secondary coverage: above 99%;
- cross-provider open-return correlation: above 0.999;
- no unexplained material adjustment-factor jumps;
- no cross-provider stitching;
- adjusted SHA-256: `bd095082899a40be28bcd5d5b3a0f263e03affca04d383012123411b25231d5d`;
- manifest SHA-256: `5a64da9036639fa34c185afb9ceabd0d55f0bb4ea873fd73791b1d83eebf3380`.

## Common execution contract

The performance comparison used 1,610 common sessions and 1,598 common eligible opens from 2019-11-26 through 2026-08-03.

- V1.0 close target;
- execution at the next common independently confirmed eligible open;
- first overlap interval starts in cash;
- ineligible opens do not advance pending allocation;
- 20 bps primary and 40 bps stress costs;
- costs use absolute BYD, ETF, and cash weight changes.

## Full-overlap result at 20 bps

| Sleeve | CAGR | Total return | Maximum drawdown | Calmar | Round trips/year |
|---|---:|---:|---:|---:|---:|
| 515180.SH | 35.07% | 581.81% | -48.74% | 0.7196 | 1.06 |
| 511010.SH | 33.87% | 544.06% | -48.54% | 0.6979 | 1.06 |
| Cash | 33.52% | 533.39% | -48.98% | 0.6845 | 1.02 |

`511010.SH` improved on cash, but its CAGR advantage was only about 0.35 percentage points. The pre-registered qualification threshold was at least 0.50 percentage points. It therefore failed cash qualification before the 515180 challenge gates were evaluated.

## Period dispersion

Period contribution is calculated as:

`candidate terminal wealth / cash terminal wealth - 1`

This is the same relative-wealth definition used in the original 515180 governance. Direct subtraction of standalone total returns is invalid because it embeds different starting wealth across calendar blocks.

| Sleeve | Development | Fixed validation | 2025+ | Largest positive share |
|---|---:|---:|---:|---:|
| 515180.SH | 1.95% | 2.75% | 2.76% | 36.98% |
| 511010.SH | 0.53% | 0.96% | 0.19% | 57.05% |

Both available ETFs had positive relative returns in all three periods and passed the 60% concentration ceiling. This did not override the frozen CAGR qualification requirement.

## Governed conclusion

- `512890.SH`: eliminated at the data-quality gate;
- `511010.SH`: canonical data passed, historical performance did not clear cash qualification;
- `515180.SH`: passed every frozen cash-qualification gate and remains the only prospective ETF sleeve;
- selected challenger: none;
- canonical BYD V1.0: unchanged;
- Issue #529 prospective ledger: unchanged and continues to accumulate evidence;
- `research_only=true`;
- `trade_ready=false`;
- fresh historical holdout: false.

The candidate universe is closed. Further historical ETF searches are not authorized from this result. The next BYD decision point is the prospective re-evaluation gate already frozen in Issue #529, not another historical asset scan.

## Sealed evidence

- artifact: `data/research/byd_defensive_sleeve_screen_v1_artifact.zip.b64`;
- artifact SHA-256: `0997467e867cbc3189292befcbfa758d442d05f389b0b39deb1caf3b2aeab7a6`;
- sealed manifest: `docs/evidence/byd_defensive_sleeve_screen/sealed_manifest.json`;
- source workflow run: `31005242952`.
