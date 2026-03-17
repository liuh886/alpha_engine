from __future__ import annotations

import types
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.modules.setdefault(
    "qlib.contrib.data.loader",
    types.SimpleNamespace(
        Alpha158DL=types.SimpleNamespace(
            get_feature_config=lambda *_args, **_kwargs: ([f"alpha{i}" for i in range(158)], None)
        )
    ),
)

from src.common import inference_features as inference  # noqa: E402


def test_resolve_features_supports_raw_profile_alpha158_plus_extra_features():
    profile = {
        "model": {
            "feature_pack": "alpha158",
            "extra_features": [
                "$close/Ref($close, 5)-1",
                "$close/Ref($close, 10)-1",
                "$close/Ref($close, 20)-1",
                "Std($close, 10)",
                "$volume/Ref($volume, 10)-1",
            ],
        }
    }
    defaults = ["f1", "f2"]

    feats = inference.resolve_inference_feature_list(profile, market_name="us", default_features=defaults)

    assert len(feats) == 163
    assert feats[-5:] == profile["model"]["extra_features"]
    assert feats[:2] != defaults


def test_resolve_features_uses_profile_market_metadata_without_hardcoded_market_defaults():
    profile = {
        "market": {
            "feature_namespace": "global_macro",
        }
    }

    feats = inference.resolve_inference_feature_list(profile, market_name="sg")

    assert feats[-2:] == [
        "$mkt_global_macro_ma20_dev",
        "$mkt_global_macro_ma60_dev",
    ]
