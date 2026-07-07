# AlphaEngine 10D Model Decision Pack

## Current decision

Current best research candidate:

```text
blend:ranker_momentum:momentum_volatility_volume:gain5_round100_leaves31_leaf10_lr0.05:ranker0.5_momentum0.5/signal_blend/original
```

Decision status:

```text
stronger_research_candidate
```

Trade-ready status:

```text
not trade-ready
```

## Evidence summary

The latest stable-signal blend evidence improved both signal strength and drawdown versus the previous ranker-grid candidates.

| Candidate | Mean ICIR | Worst drawdown | Ready ratio | Interpretation |
| --- | ---: | ---: | ---: | --- |
| #84 daily ranker/original | 0.0833 | -14.2% | 0.00 | early positive signal |
| #85 high-ICIR ranker | 0.2027 | -19.6% | 0.00 | stronger ICIR, drawdown too weak |
| #85 low-drawdown ranker | 0.1723 | -10.4% | 0.00 | lower drawdown, moderate ICIR |
| #86 best 50/50 blend | 0.2551 | -11.2% | 0.25 | strongest current research candidate |

## Gate status

The #86 best blend is meaningfully better than previous ranker candidates, but it still fails trade-guidance requirements:

- Mean ICIR remains below `0.30`.
- Ready ratio is only `0.25`, so trade-guidance gates do not pass consistently across windows.
- The evidence is still based on a small default US watchlist and four half-year OOS windows.

## Research conclusion

The current direction is working: ranker calibration plus stable signal blending improved ICIR from `0.0833` to `0.2551` while keeping worst drawdown near `-11%`.

However, the model is not ready to guide trades. It should be treated as a stronger research candidate that deserves one larger validation step: expand the universe and test whether the blend remains stable outside the default 10-symbol watchlist.

## Next recommended step

Do not continue opening small parameter-search PRs. The next result-oriented step should be:

```text
universe expansion + candidate robustness validation
```

Minimum requirements:

- Run the #86 best blend on a broader 50/100-symbol US watchlist.
- Keep the same rolling-window framework.
- Compare against the current default-universe result.
- Report mean ICIR, Rank IC, spread, worst drawdown, positive ICIR ratio, positive spread ratio, and ready ratio.
- Do not claim trade readiness unless ICIR and ready ratio gates both pass.
