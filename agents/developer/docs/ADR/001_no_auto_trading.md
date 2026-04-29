# ADR 001: No Full Auto-Execution

**Date**: 2026-03-01
**Status**: Accepted

## Context
The system is an AI-powered trading assistant. Users are tempted to connect the recommendations directly to a broker for auto-execution to achieve a fully passive trading system.

## Decision
We explicitly **ban** any direct broker auto-order execution functionality in the core engine. The system will strictly retain a "Human-in-the-loop" constraint. 

## Consequences
- **Positive**: We isolate the system from asymmetric financial risks caused by model hallucinations or data pipeline bugs.
- **Positive**: Simplifies the scope to focus entirely on Alpha generation, explanation, and reporting.
- **Negative**: Users looking for a "set it and forget it" money printer will have to manually execute the trades based on system output.
