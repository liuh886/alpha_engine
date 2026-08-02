# v4.2 SGOV recovery-release experiment status

**Started:** 2026-08-02  
**Branch:** `agent/v4-2-sgov-recovery-release`  
**Status:** awaiting governed-data execution

## Decision before results

The experiment admits exactly three variants:

1. SGOV to QQQI at executed state 1;
2. 25% SGOV to 25% TQQQ on the frozen leverage precursor;
3. staged QQQI release followed by the same 25% TQQQ precursor.

No other weights, thresholds or confirmation lengths are permitted. The current v4.2 baseline remains unchanged regardless of the retrospective result. A passing candidate can only enter prospective monitoring.

## Primary question

Can a release rule reduce the static blended profile's recovery lag from 57 sessions to no more than 30 sessions while retaining at least 2 percentage points of median protection across the five largest v4.2 troughs?

## Secondary question

If limited early TQQQ improves recovery, is the benefit positive across at least 60% of precursor episodes and not concentrated in one rebound?
