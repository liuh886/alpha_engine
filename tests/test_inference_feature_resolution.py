from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import inference  # noqa: E402


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

