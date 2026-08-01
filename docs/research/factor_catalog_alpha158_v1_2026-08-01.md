# Governed Factor Catalog: Qlib Alpha158 v1

## Decision

The intended public feature set is **Qlib Alpha158**. `Alpha161` was a wording
error and is not retained as a namespace or alias.

This foundation creates an immutable catalog for:

- `qlib_alpha158.*` public formula definitions;
- future `ae.*` user-authored factors;
- future `legacy261.*` recovered historical factors.

Only Alpha158 is imported in this first PR.

## Canonical source

The catalog calls the installed `pyqlib` implementation directly:

```python
Alpha158DL.get_feature_config(ALPHA158_CONFIG)
```

with the same default configuration used by Qlib's `Alpha158` handler:

- K-bar features enabled;
- current OPEN, HIGH, LOW and VWAP price features;
- default rolling operators and windows;
- no custom AlphaEngine subset or reordered field list.

The build fails unless Qlib returns exactly 158 unique names and 158 matching
expressions. The installed `pyqlib` version and upstream source reference are
stored with every definition.

## Factor identity

Every definition records:

- namespaced factor ID and version;
- exact expression;
- required raw fields;
- US/CN applicability;
- minimum lookback;
- availability lag;
- adjustment requirement;
- missing-value policy;
- source/version/reference;
- immutable implementation SHA-256;
- validation status.

All imported Alpha158 definitions begin as `unvalidated_formula`. Formula
availability does not imply economic support.

## Price semantics

Alpha158 is bound to the `adjusted` price requirement established by
`corporate_action_store_v1`. The source panel must provide OPEN, HIGH, LOW,
CLOSE, VWAP and VOLUME under one declared adjustment contract. Raw execution
prices cannot be silently substituted.

## Existing asset inventory

The repository contains older Alpha158 workflow references, training scripts,
FactorRegistry history and a documented legacy 261-factor scan. The inventory
script records file presence and hashes but does not infer that every old output
or metric still has a recoverable formula.

A later migration step must classify each historical asset as:

- complete formula available;
- generated output only;
- metrics/evidence only;
- absent from the current checkout.

No formula will be reverse-engineered from historical returns.

## Next slices

1. compute an Alpha158 panel on manifest-bound US 87 and CN 130 providers;
2. verify chunked/full-panel parity and no-lookahead mutation behavior;
3. publish per-symbol/per-feature coverage matrices;
4. register definitions and evidence identities in FactorRegistry v2;
5. recover user-authored and legacy261 formulas without overwriting failed
   research history.

No bulk factor selection, weight learning or trade-ready promotion is included.
