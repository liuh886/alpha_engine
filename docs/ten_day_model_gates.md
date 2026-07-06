# Ten-day model gates

AlphaEngine should keep candidates in research status until fixed-ten-day evidence is strong enough.

Required gates:

- ICIR at least 0.30
- Rank IC at least 0.02
- Positive IC ratio at least 0.55
- Top minus bottom spread above zero
- Sharpe above zero
- Max drawdown no worse than -0.15
- Direction diagnostic says keep score
- Return input is raw forward return with horizon 10

Next work:

1. Add risk controls around the current historical momentum baseline.
2. Add a real ranking model rather than only transforming regression scores.
3. Add an out-of-sample top-bucket model and evaluate it only with raw ten-day returns.

Local smoke path:

1. Run 01_factor_research.ipynb.
2. Run end_to_end_training_pipeline.ipynb.
3. Confirm artifacts/evidence/notebook_10d_lab has a JSON result.
