from __future__ import annotations

from pathlib import Path

script = Path("scripts/run_cn130_pit_fundamental_model.py")
text = script.read_text(encoding="utf-8")
old = '    scored["fundamental_composite"] = scored[percentile_columns].mean(axis=1, skipna=True)\n    scored.loc[~scored["usable_fundamental"], "fundamental_composite"] = np.nan\n'
new = '    scored["fundamental_composite"] = scored[percentile_columns].mean(axis=1, skipna=True)\n    usable = scored["usable_fundamental"].fillna(False).astype(bool)\n    scored["usable_fundamental"] = usable\n    scored.loc[~usable, "fundamental_composite"] = np.nan\n'
if old not in text:
    raise RuntimeError("expected score_snapshot boolean mask block not found")
script.write_text(text.replace(old, new), encoding="utf-8")

test = Path("tests/test_cn130_pit_fundamental_model.py")
text = test.read_text(encoding="utf-8")
old_import = '    latest_pit_snapshot,\n    robust_growth,\n)\n'
new_import = '    latest_pit_snapshot,\n    robust_growth,\n    score_snapshot,\n)\n'
if old_import not in text:
    raise RuntimeError("expected import block not found")
text = text.replace(old_import, new_import)
addition = '''\n\ndef test_score_snapshot_normalizes_nullable_object_boolean_mask() -> None:\n    frame = pd.DataFrame(\n        {\n            "sector": ["A", "A", "A"],\n            "fiscal_period": ["FY", "FY", "FY"],\n            "staleness_days": [30, 30, 30],\n            "usable_fundamental": pd.Series([True, False, None], dtype="object"),\n            "revenue_yoy": [0.1, 0.2, 0.3],\n            "net_income_yoy_robust": [0.1, 0.2, 0.3],\n            "net_margin": [0.1, 0.2, 0.3],\n            "roe_proxy": [0.1, 0.2, 0.3],\n            "asset_turnover": [0.1, 0.2, 0.3],\n            "inverse_leverage": [0.1, 0.2, 0.3],\n        }\n    )\n    scored = score_snapshot(frame)\n    assert scored["usable_fundamental"].dtype == bool\n    assert pd.notna(scored.loc[0, "fundamental_composite"])\n    assert pd.isna(scored.loc[1, "fundamental_composite"])\n    assert pd.isna(scored.loc[2, "fundamental_composite"])\n'''
if "test_score_snapshot_normalizes_nullable_object_boolean_mask" not in text:
    text += addition
test.write_text(text, encoding="utf-8")
