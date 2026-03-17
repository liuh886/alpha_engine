from __future__ import annotations

from typing import Any

from src.common.market import get_region_for_market

COMMON_INFERENCE_FEATURES = [
    "$close/Ref($close, 1)-1",
    "$close/Ref($close, 5)-1",
    "$close/Ref($close, 10)-1",
    "$close/Ref($close, 20)-1",
    "$close/Mean($close, 5)-1",
    "$close/Mean($close, 20)-1",
    "$close/Mean($close, 60)-1",
    "Std($close, 20)/Mean($close, 20)",
    "($high-$low)/$close",
    "$volume/Mean($volume, 5)",
    "$volume/Mean($volume, 20)",
]

MARKET_INFERENCE_FEATURE_TEMPLATES = [
    "$mkt_{feature_namespace}_ma20_dev",
    "$mkt_{feature_namespace}_ma60_dev",
]


def ensure_feature_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def build_alpha158_plus_extra_features(extra_features: Any) -> list[str]:
    from qlib.contrib.data.loader import Alpha158DL

    alpha_features = Alpha158DL.get_feature_config(
        {
            "kbar": {},
            "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
            "rolling": {},
        }
    )[0]
    return list(alpha_features) + ensure_feature_list(extra_features)


def resolve_feature_namespace(profile: dict[str, Any] | None, market_name: str) -> str:
    profile = profile if isinstance(profile, dict) else {}
    market_meta = profile.get("market", {}) if isinstance(profile.get("market"), dict) else {}
    meta = profile.get("meta", {}) if isinstance(profile.get("meta"), dict) else {}

    namespace = (
        market_meta.get("feature_namespace")
        or market_meta.get("feature_region")
        or market_meta.get("region")
        or meta.get("feature_namespace")
    )
    if namespace:
        return str(namespace).strip().lower()
    return get_region_for_market(market_name)


def build_default_inference_features(market_name: str, profile: dict[str, Any] | None = None) -> list[str]:
    feature_namespace = resolve_feature_namespace(profile, market_name)
    market_features = [
        template.format(feature_namespace=feature_namespace)
        for template in MARKET_INFERENCE_FEATURE_TEMPLATES
    ]
    return list(COMMON_INFERENCE_FEATURES) + market_features


def resolve_inference_feature_list(
    profile: dict[str, Any] | None,
    market_name: str,
    default_features: list[str] | None = None,
) -> list[str]:
    if not isinstance(profile, dict):
        return list(default_features or build_default_inference_features(market_name))

    compiled_feats = (
        (profile.get("task", {}) or {})
        .get("dataset", {})
        .get("kwargs", {})
        .get("handler", {})
        .get("kwargs", {})
        .get("data_loader", {})
        .get("kwargs", {})
        .get("config", {})
        .get("feature")
    )
    if compiled_feats and isinstance(compiled_feats, list):
        return list(compiled_feats)

    model = profile.get("model", {}) if isinstance(profile.get("model", {}), dict) else {}
    feature_pack = str(model.get("feature_pack") or "").lower()
    if feature_pack == "alpha158":
        return build_alpha158_plus_extra_features(model.get("extra_features"))

    model_features = model.get("features")
    if model_features:
        return ensure_feature_list(model_features)

    return list(default_features or build_default_inference_features(market_name, profile))
