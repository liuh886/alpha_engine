from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderCapability:
    """Machine-readable semantics for one market-data adapter.

    ``source_family`` identifies the upstream data source. Two adapters that
    share a source family are alternate transports, not independent evidence.
    """

    name: str
    source_family: str
    independent_group: str
    markets: tuple[str, ...]
    price_mode: str
    volume_unit: str
    amount_unit: str
    corporate_actions: bool
    trade_calendar: bool
    credential_env: str | None = None
    research_only: bool = True
    usage_note: str = ""

    @property
    def credentialed(self) -> bool:
        return self.credential_env is not None

    @property
    def available(self) -> bool:
        if self.credential_env is None:
            return True
        return bool(os.getenv(self.credential_env, "").strip())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["markets"] = list(self.markets)
        payload["credentialed"] = self.credentialed
        payload["available"] = self.available
        return payload


_PROVIDER_CATALOG: dict[str, ProviderCapability] = {
    "tushare": ProviderCapability(
        name="tushare",
        source_family="tushare_pro",
        independent_group="tushare_pro",
        markets=("cn",),
        price_mode="raw_plus_adjustment_factor",
        volume_unit="shares",
        amount_unit="CNY",
        corporate_actions=True,
        trade_calendar=True,
        credential_env="TUSHARE_TOKEN",
        usage_note="Credentialed managed CN source; token permissions determine endpoint access.",
    ),
    "akshare_sina": ProviderCapability(
        name="akshare_sina",
        source_family="sina_finance",
        independent_group="sina_finance",
        markets=("cn",),
        price_mode="qfq_adjusted",
        volume_unit="shares",
        amount_unit="CNY",
        corporate_actions=False,
        trade_calendar=False,
        usage_note=(
            "Independent public Sina transport through AKShare; throttled because "
            "repeated requests can trigger temporary IP blocking."
        ),
    ),
    "akshare": ProviderCapability(
        name="akshare",
        source_family="eastmoney",
        independent_group="eastmoney",
        markets=("cn",),
        price_mode="qfq_adjusted",
        volume_unit="shares",
        amount_unit="CNY",
        corporate_actions=False,
        trade_calendar=False,
        usage_note="Public Eastmoney transport through AKShare; endpoint stability is not guaranteed.",
    ),
    "efinance": ProviderCapability(
        name="efinance",
        source_family="eastmoney",
        independent_group="eastmoney",
        markets=("cn",),
        price_mode="qfq_adjusted",
        volume_unit="shares",
        amount_unit="CNY",
        corporate_actions=False,
        trade_calendar=False,
        usage_note="Alternate Eastmoney transport; not independent corroboration for AKShare.",
    ),
    "baostock": ProviderCapability(
        name="baostock",
        source_family="baostock",
        independent_group="baostock",
        markets=("cn",),
        price_mode="raw_unadjusted",
        volume_unit="shares",
        amount_unit="CNY",
        corporate_actions=False,
        trade_calendar=False,
        usage_note="Independent historical fallback with bounded socket behaviour.",
    ),
    "yfinance": ProviderCapability(
        name="yfinance",
        source_family="yahoo_finance",
        independent_group="yahoo_finance",
        markets=("cn", "hk", "us"),
        price_mode="provider_adjusted",
        volume_unit="shares",
        amount_unit="synthetic_close_times_volume",
        corporate_actions=True,
        trade_calendar=False,
        research_only=True,
        usage_note="Research/personal-use fallback; synthetic amount is not reported turnover.",
    ),
}


def provider_capability(name: str) -> ProviderCapability:
    key = str(name or "").strip().lower()
    if key in _PROVIDER_CATALOG:
        return _PROVIDER_CATALOG[key]
    return ProviderCapability(
        name=key or "unknown",
        source_family=key or "unknown",
        independent_group=key or "unknown",
        markets=(),
        price_mode="unknown",
        volume_unit="unknown",
        amount_unit="unknown",
        corporate_actions=False,
        trade_calendar=False,
        usage_note="Unregistered provider; no promotion claim is permitted.",
    )


def provider_manifest_entry(name: str) -> dict[str, Any]:
    return provider_capability(name).to_dict()


def independent_provider_names(names: list[str]) -> list[str]:
    """Return the first provider from each independent upstream group."""

    selected: list[str] = []
    seen: set[str] = set()
    for name in names:
        capability = provider_capability(name)
        if capability.independent_group in seen:
            continue
        seen.add(capability.independent_group)
        selected.append(capability.name)
    return selected
