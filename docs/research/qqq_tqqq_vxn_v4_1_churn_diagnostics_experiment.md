# QQQ/TQQQ v4.1 churn and dwell-time diagnostics

## Question

Does the frozen v4.1 VXN leverage veto create recurring, economically harmful short exits and rapid re-entry cycles?

## Boundary

This is a diagnostic-only experiment. It changes no:

- price signal;
- VIX or VXN threshold;
- state transition;
- TQQQ weight;
- execution convention;
- transaction-cost assumption.

No cooldown, hysteresis, persistence or minimum-holding rule is tested here.

## Fixed diagnostics

The analysis reports:

- contiguous leveraged-state dwell times;
- leveraged episodes lasting no more than 5, 10 or 20 sessions;
- gap from each leverage exit to the next leverage entry;
- re-entry cycles occurring in the same calendar month;
- turnover and explicit transaction cost by executed transition reason;
- every exit caused uniquely by VXN while the VIX-only baseline remains leveraged;
- relative VXN-versus-VIX return while positions differ;
- QQQ and TQQQ returns over 1, 5, 10 and 20 sessions after each VXN-only exit.

A five-session re-entry window is predeclared only for diagnosis. It is not a candidate parameter and cannot be selected or changed based on the result.

## Decision gate

A separate hysteresis hypothesis is admissible only if VXN-only rapid exits are:

1. recurring rather than isolated;
2. followed by quick re-entry;
3. economically harmful after transaction costs;
4. distinguishable from longer exits that genuinely avoid losses.

Even if the gate is met, the next experiment may test only one simple predeclared rule. No parameter grid is allowed.

Status:

- `research_only=true`;
- `trade_ready=false`;
- `diagnostic_only=true`;
- `strategy_rule_changed=false`.
