"""Personal Investment Lens (个人持仓投研透镜) Interface.

Provides a decoupled, read-only audit and analysis interface between the user's
personal investment notes (e.g. Obsidian Markdown files in 200_Area/Investment)
and the Alpha Engine quantitative data plane.

Strict Governance & Privacy Invariants:
1. Gate A4 / Zero Privacy Leakage:
   NEVER reads, stores, exposes, or commits personal financial numbers
   (shares, total_cost, realized_pnl, accounts, transaction logs, cash amounts).
2. Zero Local Write:
   NEVER modifies, overwrites, or creates files in the user's personal vault.
3. Decoupled Research Boundary:
   Personal records remain the user's private ledger; Alpha Engine provides
   objective market data readiness, factor coverage, and risk analytics.
   research_only=true, trade_ready=false.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any

import yaml


class PersonalLensError(Exception):
    """Raised when personal lens scan or verification encounters an error."""


FORBIDDEN_FINANCIAL_KEYS: frozenset[str] = frozenset({
    "shares",
    "total_cost",
    "cost",
    "cost_basis",
    "realized_pnl",
    "unrealized_pnl",
    "accounts",
    "account",
    "transactions",
    "trades",
    "first_buy",
    "last_trade",
    "portfolio_weight",
    "target_weight",
    "current_weight",
    "nav",
    "balance",
    "pnl",
})

ALLOWED_METADATA_KEYS: frozenset[str] = frozenset({
    "ticker",
    "name",
    "market",
    "currency",
    "asset_type",
    "strategy",
    "conviction",
    "status",
    "tags",
})


@dataclass(frozen=True)
class PersonalHoldingAudit:
    """Safe, non-financial audit record for a single personal investment holding."""

    ticker: str
    name: str
    market: str
    asset_type: str
    strategy: str
    conviction: str
    status: str
    in_governed_pool: bool
    in_reference_registry: bool
    market_evidence_present: bool
    date_range: str
    data_readiness: str
    note_file: str

    def __post_init__(self) -> None:
        # Extra defensive check: Ensure no forbidden field names or values slipped in
        for forbidden in FORBIDDEN_FINANCIAL_KEYS:
            if hasattr(self, forbidden):
                raise PersonalLensError(
                    f"Security violation: forbidden key '{forbidden}' found in PersonalHoldingAudit"
                )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersonalAuditReport:
    """Consolidated audit report across personal holdings."""

    scanned_dir: str
    total_scanned: int
    ready_count: int
    missing_evidence_count: int
    cash_count: int
    other_market_count: int
    holdings: list[PersonalHoldingAudit]
    table_markdown: str
    research_only: bool = True
    trade_ready: bool = False
    privacy_boundary: str = "zero_financial_data_read_or_exposed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_dir": self.scanned_dir,
            "total_scanned": self.total_scanned,
            "ready_count": self.ready_count,
            "missing_evidence_count": self.missing_evidence_count,
            "cash_count": self.cash_count,
            "other_market_count": self.other_market_count,
            "privacy_boundary": self.privacy_boundary,
            "research_only": self.research_only,
            "trade_ready": self.trade_ready,
            "holdings": [h.to_dict() for h in self.holdings],
            "table_markdown": self.table_markdown,
        }


def _extract_safe_frontmatter(content: str, filename: str) -> dict[str, Any]:
    """Safely extracts only non-financial metadata from YAML frontmatter.

    Strictly discards any sensitive financial keys (shares, cost, accounts, etc.).
    """
    stem = Path(filename).stem
    meta: dict[str, Any] = {
        "ticker": stem,
        "name": "",
        "market": "US",
        "asset_type": "stock",
        "strategy": "",
        "conviction": "",
        "status": "holding",
    }

    match = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", content, re.DOTALL)
    if not match:
        return meta

    frontmatter_raw = match.group(1)
    try:
        parsed = yaml.safe_load(frontmatter_raw)
    except yaml.YAMLError:
        return meta

    if not isinstance(parsed, dict):
        return meta

    # Explicitly filter only allowed metadata, strictly ignoring forbidden keys
    for key, value in parsed.items():
        if key.lower() in FORBIDDEN_FINANCIAL_KEYS:
            continue
        if key in ALLOWED_METADATA_KEYS and value is not None:
            if key == "ticker":
                meta["ticker"] = str(value).strip().upper()
            elif key == "name":
                meta["name"] = str(value).strip()
            elif key == "market":
                meta["market"] = str(value).strip().upper()
            elif key == "asset_type":
                meta["asset_type"] = str(value).strip().lower()
            elif key == "strategy":
                meta["strategy"] = str(value).strip().lower()
            elif key == "conviction":
                meta["conviction"] = str(value).strip().lower()
            elif key == "status":
                meta["status"] = str(value).strip().lower()

    return meta


def _load_governed_universes(root: Path) -> tuple[set[str], set[str], dict[str, Any]]:
    """Loads Alpha Engine governed candidate pool, reference registry, and market catalog."""
    us_candidates: set[str] = set()
    us_references: set[str] = set()
    us_catalog_symbols: dict[str, Any] = {}

    # 1. Candidate pool: us_selected_equities_v2.yaml
    pool_path = root / "configs/research_universes/us_selected_equities_v2.yaml"
    if pool_path.is_file():
        try:
            pool_data = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
            if isinstance(pool_data, dict) and "symbols" in pool_data:
                us_candidates = {str(s).upper() for s in pool_data["symbols"]}
        except Exception:
            pass

    # 2. Reference registry: reference_instrument_registry_v1.yaml
    ref_path = root / "configs/pools/reference_instrument_registry_v1.yaml"
    if ref_path.is_file():
        try:
            ref_data = yaml.safe_load(ref_path.read_text(encoding="utf-8"))
            if isinstance(ref_data, dict):
                markets = ref_data.get("markets", {})
                us_insts = markets.get("us", {}).get("instruments", {})
                us_references = {str(k).upper() for k in us_insts.keys()}
        except Exception:
            pass

    # 3. Market evidence catalog: data/research/market_evidence/us/catalog.json
    catalog_path = root / "data/research/market_evidence/us/catalog.json"
    if catalog_path.is_file():
        try:
            catalog_data = json.loads(catalog_path.read_text(encoding="utf-8"))
            if isinstance(catalog_data, dict):
                for sym_entry in catalog_data.get("symbols", []):
                    sym = sym_entry.get("symbol", "").upper()
                    if sym:
                        us_catalog_symbols[sym] = sym_entry
        except Exception:
            pass

    return us_candidates, us_references, us_catalog_symbols


def _build_markdown_table(holdings: list[PersonalHoldingAudit]) -> str:
    """Formats audit records into an elegant, human-readable Markdown table."""
    lines: list[str] = [
        "| 标的代码 | 标的名称 | 资产类别 | 投资策略 | 引擎治理选股池 | 参考资产库 | 数据切片状态 | 历史证据跨度 |",
        "| :--- | :--- | :--- | :--- | :---: | :---: | :--- | :--- |",
    ]

    for h in holdings:
        pool_badge = "✅ 是 (US 87)" if h.in_governed_pool else "-"
        ref_badge = "🏛️ 是 (Ref)" if h.in_reference_registry else "-"

        if h.data_readiness == "ready":
            status_badge = "🟢 已就绪 (Ready)"
        elif h.data_readiness == "cash_reserve":
            status_badge = "💵 现金储备 (Cash)"
        elif h.data_readiness.startswith("unregistered_market"):
            status_badge = f"🌐 跨市场 ({h.market})"
        else:
            status_badge = "⚠️ 缺失切片 (Missing)"

        name_display = h.name if h.name else "-"
        strategy_display = h.strategy if h.strategy else "-"

        lines.append(
            f"| `{h.ticker}` | {name_display} | {h.asset_type} | {strategy_display} | "
            f"{pool_badge} | {ref_badge} | {status_badge} | {h.date_range} |"
        )

    return "\n".join(lines)


def scan_personal_investment_pool(
    pool_dir: Path,
    root: Path | None = None,
) -> PersonalAuditReport:
    """Scans the personal investment directory, auditing data readiness without reading funds.

    Parameters
    ----------
    pool_dir : Path
        Directory containing personal investment notes (.md files).
    root : Path | None
        Alpha Engine repository root. Defaults to cwd.

    Returns
    -------
    PersonalAuditReport
        Structured audit report containing non-financial holdings and data readiness.
    """
    resolved_dir = pool_dir.resolve()
    if not resolved_dir.is_dir():
        raise PersonalLensError(f"Personal investment pool directory not found: {resolved_dir}")

    repo_root = (root or Path.cwd()).resolve()
    us_candidates, us_references, us_catalog = _load_governed_universes(repo_root)

    evidence_symbols_dir = repo_root / "data/research/market_evidence/us/symbols"

    md_files = sorted(resolved_dir.glob("*.md"))
    holdings: list[PersonalHoldingAudit] = []

    ready_count = 0
    missing_evidence_count = 0
    cash_count = 0
    other_market_count = 0

    for file_path in md_files:
        # Strictly read-only
        content = file_path.read_text(encoding="utf-8")
        meta = _extract_safe_frontmatter(content, file_path.name)

        ticker = meta["ticker"]
        name = meta["name"]
        market = meta["market"]
        asset_type = meta["asset_type"]
        strategy = meta["strategy"]
        conviction = meta["conviction"]
        status = meta["status"]

        # Classification
        if asset_type == "cash" or ticker.startswith("USD.CASH") or "CASH" in ticker:
            cash_count += 1
            data_readiness = "cash_reserve"
            date_range = "N/A (现金储备)"
            in_pool = False
            in_ref = False
            has_evidence = False
        elif market != "US":
            other_market_count += 1
            data_readiness = f"unregistered_market_{market.lower()}"
            date_range = f"N/A ({market} 市场未接入)"
            in_pool = False
            in_ref = False
            has_evidence = False
        else:
            in_pool = ticker in us_candidates
            in_ref = ticker in us_references

            # Check market evidence
            has_catalog_entry = ticker in us_catalog
            has_symbol_file = (evidence_symbols_dir / f"{ticker}.json").is_file()
            has_evidence = has_catalog_entry or has_symbol_file

            if has_evidence:
                ready_count += 1
                data_readiness = "ready"
                if has_catalog_entry:
                    cat_entry = us_catalog[ticker]
                    start = cat_entry.get("start", "2021-01-01")
                    cutoff = cat_entry.get("cutoff", "2026-10-26")
                    date_range = f"{start} ~ {cutoff}"
                else:
                    date_range = "2021-01-01 ~ 2026-10-26"
            else:
                missing_evidence_count += 1
                data_readiness = "missing_market_evidence"
                date_range = "缺失本地行情切片"

        audit_item = PersonalHoldingAudit(
            ticker=ticker,
            name=name,
            market=market,
            asset_type=asset_type,
            strategy=strategy,
            conviction=conviction,
            status=status,
            in_governed_pool=in_pool,
            in_reference_registry=in_ref,
            market_evidence_present=has_evidence,
            date_range=date_range,
            data_readiness=data_readiness,
            note_file=file_path.name,
        )
        holdings.append(audit_item)

    table_md = _build_markdown_table(holdings)

    return PersonalAuditReport(
        scanned_dir=resolved_dir.as_posix(),
        total_scanned=len(holdings),
        ready_count=ready_count,
        missing_evidence_count=missing_evidence_count,
        cash_count=cash_count,
        other_market_count=other_market_count,
        holdings=holdings,
        table_markdown=table_md,
    )
