"""Disposable product projection of reviewed RDI evidence, never a prediction.

No provider calls, model imports, evaluation or source mutation on this path.
The archived source inventory is not a daily coverage certificate.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import yaml

READINESS = "docs/evidence/ashare_rdi_phase2/csi300_input_readiness_2026-10-24.json"
BASELINE = "docs/evidence/ashare_rdi_phase2/csi300_price_only_descriptive_2026-10-24.json"
SOURCES = "configs/research_experiments/ashare_rdi_phase2_sources.yaml"
SECTORS = "configs/research_experiments/ashare_rdi_phase2_sector_candidates.yaml"
PRICE = "data/csv_source/000300.csv"
PROTOCOL = "docs/research/ashare_rdi_phase2_protocol.md"


def build_research_briefing(repo_root: Path) -> dict[str, object]:
    """Expose the dated review and only its exact-source descriptive results.

    Missing files raise: the consumer must show unavailable, not an older success.
    Changed/contradictory sources retain review metadata but suppress statistics.
    Advancing the inventory cannot by itself promote the study or certify data.
    """
    evidence: dict[str, str] = {}

    def read(path: str) -> dict:
        raw = (repo_root / path).read_bytes()
        evidence[path] = hashlib.sha256(raw).hexdigest()
        return yaml.safe_load(raw) if path.endswith(".yaml") else json.loads(raw)

    readiness, baseline, sources, sectors = (read(p) for p in (READINESS, BASELINE, SOURCES, SECTORS))
    for record in (readiness, baseline, sources, sectors):
        if record.get("research_only") is not True or record.get("trade_ready") is not False:
            raise ValueError("RDI research boundary is invalid")
    # Tree identity works with sparse checkouts without downloading price blobs.
    commit, price_blob = subprocess.check_output(
        ["git", "rev-parse", "HEAD", f"HEAD:{PRICE}"], cwd=repo_root, text=True,
    ).strip().splitlines()
    if (repo_root / PRICE).is_file():
        raw_price = (repo_root / PRICE).read_bytes()
        price_blob = hashlib.sha1(b"blob " + str(len(raw_price)).encode() + b"\0" + raw_price).hexdigest()
    consistent = (
        price_blob == readiness.get("source_git_blob_sha1") == baseline.get("source_git_blob_sha1")
        and readiness.get("last_price_date") == baseline.get("last_price_session")
        and readiness.get("eligible_rows_from_2005_04_08") == baseline.get("rows")
        and readiness.get("canonical_symbol") == "000300.SH"
        and baseline.get("source_repo_path") == PRICE
        and baseline.get("status") == "price_only_descriptive_not_out_of_sample"
        and baseline.get("event_rdi_evaluated") is False
        and baseline.get("predictive_skill_established") is False
        and readiness.get("predictive_power_established") is False
        and readiness.get("rdi_scores_produced") is False
        and baseline.get("lookback_sessions") == 60
        and baseline.get("drawdown_threshold") == -0.1
        and baseline.get("severe_loss_threshold") == -0.05
    )
    results = baseline.get("results", [])
    if [r.get("horizon_sessions") for r in results] != [7, 14, 28]:
        consistent = False
    for row in results:
        for key in ("drawdown_at_least_threshold", "other"):
            group = row.get(key, {})
            n, probability = group.get("observations"), group.get("p_severe_loss")
            if (not isinstance(n, int) or isinstance(n, bool) or n <= 0
                    or not isinstance(probability, (int, float))
                    or isinstance(probability, bool) or not 0 <= probability <= 1):
                consistent = False
    families = sources.get("event_families", {})
    if not families or not sectors.get("candidates"):
        raise ValueError("RDI evidence inventory is empty")
    return {
        "schema_version": "1.0.0",
        "research_only": True,
        "trade_ready": False,
        "status": "not_validated" if consistent else "evidence_mismatch",
        "repository_commit": commit,
        "price_source_git_blob_sha1": price_blob,
        "reviewed_at": readiness["reviewed_at"],
        "benchmark": "CSI300 / 000300.SH",
        "reviewed_price_cutoff": readiness["last_price_date"],
        "reviewed_price_rows": readiness["eligible_rows_from_2005_04_08"],
        "event_families": [
            {"id": key, "source": row["source"], "readiness": row["readiness"],
             "historical_pit_verified": row.get("pit_verified") is True}
            for key, row in families.items()
        ],
        "sector_candidates": [
            {"symbol": row["symbol"], "sector": row["sector"], "admitted": False}
            for row in sectors["candidates"]
        ],
        "historical_comparison": [
            {"horizon_sessions": row["horizon_sessions"],
             "drawdown_loss_frequency": row["drawdown_at_least_threshold"]["p_severe_loss"],
             "other_loss_frequency": row["other"]["p_severe_loss"],
             "drawdown_observations": row["drawdown_at_least_threshold"]["observations"],
             "other_observations": row["other"]["observations"]}
            for row in results
        ] if consistent else [],
        "evidence": [{"path": path, "sha256": digest} for path, digest in evidence.items()],
        "protocol_path": PROTOCOL,
    }
