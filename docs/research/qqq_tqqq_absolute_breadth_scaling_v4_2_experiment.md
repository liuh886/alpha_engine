# QQQ/TQQQ absolute-breadth soft-scaling v4.2

## Question

Can QQQE's own absolute trend improve the amount of leverage used inside the frozen v4.1 recovery state?

## Difference from the rejected breadth gate

The rejected v4 experiment required QQQE to outperform QQQ and blocked TQQQ entirely when relative breadth was weak.

This experiment does neither:

- it never compares QQQE with QQQ;
- it never blocks the recovery state;
- weak or unconfirmed breadth retains 50% TQQQ / 50% QQQ;
- confirmed breadth permits 75% TQQQ / 25% QQQ.

## Frozen definition

Breadth is confirmed when:

- QQQE closes above its own 20-session moving average; and
- QQQE's five-session return is positive.

These are the only tested windows. The 50% and 75% weights are inherited from previously completed experiments. No grid is permitted.

## Frozen strategy

The complete v4.1 decision state trace is identical between baseline and challenger:

- price repair unchanged;
- VIX rules unchanged;
- VXN entry veto and immediate exit unchanged;
- close signal and next-open execution unchanged;
- 10 bps cost per turnover unit.

Only the TQQQ weight inside source state 2 changes according to the prior close's absolute-breadth confirmation.

## Decision gate

Add the factor only if it produces a clear risk-adjusted improvement after costs, avoids material CAGR sacrifice and remains reasonably stable across predeclared periods. A smoother equity curve alone is insufficient.

Status:

- `research_only=true`;
- `trade_ready=false`.
