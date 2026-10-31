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

READINESS = "docs/evidence/ashare_rdi_phase2/rdi_product_review_2026-10-31.json"
BASELINE = "docs/evidence/ashare_rdi_phase2/csi300_price_recomputation_2026-10-31.json"
SOURCES = "configs/research_experiments/ashare_rdi_phase2_sources.yaml"
SECTORS = "configs/research_experiments/ashare_rdi_phase2_sector_candidates.yaml"
PRICE = "data/research/ashare_rdi/price_sources/sina_2026-10-31/response.js.gz"
CONTRACT = "configs/research_experiments/ashare_rdi_csi300_price_repair_2026-10-31.json"
SOURCE_MANIFEST = "data/research/ashare_rdi/price_sources/sina_2026-10-31/manifest.json"
PROTOCOL = "docs/research/ashare_rdi_price_reconstruction_2026-10-31.md"


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

    review, receipt, sources, sectors, contract, source = (
        read(p) for p in (READINESS, BASELINE, SOURCES, SECTORS, CONTRACT, SOURCE_MANIFEST))
    evidence[PROTOCOL] = hashlib.sha256((repo_root / PROTOCOL).read_bytes()).hexdigest()
    for record in (review, receipt, sources, sectors, contract, source):
        if record.get("research_only") is not True or record.get("trade_ready") is not False:
            raise ValueError("RDI research boundary is invalid")
    commit, archive_blob = subprocess.check_output(
        ["git", "rev-parse", "HEAD", f"HEAD:{PRICE}"], cwd=repo_root, text=True,
    ).strip().splitlines()
    archive_matches = archive_blob == review.get("source_archive_git_blob_sha1")
    if (repo_root / PRICE).is_file():
        archive_matches = archive_matches and hashlib.sha256(
            (repo_root / PRICE).read_bytes()).hexdigest() == source.get("archive_sha256")
    baseline = receipt.get("full_history_descriptive", {})
    consistent = (
        review.get("schema_version") == "rdi_product_review_binding_v1"
        and review.get("rdi_validated") is False
        and all(review.get("input_sha256", {}).get(path) == evidence[path]
                for path in (BASELINE, SOURCES, SECTORS, CONTRACT, SOURCE_MANIFEST, PROTOCOL))
        and archive_matches
        and source.get("canonical_symbol") == contract.get("canonical_symbol") == "000300.SH"
        and source.get("price_basis") == contract.get("price_basis") == receipt.get("price_basis") == "unadjusted_index_points"
        and source.get("historical_first_availability_verified") is False
        and receipt.get("historical_first_availability_verified") is False
        and receipt.get("event_study_ready") is False
        and receipt.get("predictive_skill_established") is False
        and receipt.get("legacy_source_overwritten") is False
        and receipt.get("status") == "price_only_reconstruction_verified_not_rdi_validated"
        and receipt.get("contract_sha256") == evidence[CONTRACT]
        and receipt.get("source_manifest_sha256") == evidence[SOURCE_MANIFEST]
        and receipt.get("source_response_sha256") == source.get("raw_response_sha256")
        and receipt.get("output_sha256") == review.get("price_output_sha256")
        and receipt.get("legacy_git_blob_sha1") == contract.get("legacy_git_blob_sha1")
        and receipt.get("cutoff") == source.get("cutoff") == contract.get("cutoff") == review.get("price_cutoff") == baseline.get("last_price_session")
        and receipt.get("repairs", {}).get("output_rows") == review.get("price_rows") == baseline.get("rows")
        and baseline.get("status") == "price_only_descriptive_not_out_of_sample"
        and baseline.get("event_rdi_evaluated") is False
        and baseline.get("predictive_skill_established") is False
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
        "schema_version": "1.1.0",
        "research_only": True,
        "trade_ready": False,
        "status": "not_validated" if consistent else "evidence_mismatch",
        "repository_commit": commit,
        "retained_source_git_blob_sha1": receipt["legacy_git_blob_sha1"],
        "price_output_sha256": review["price_output_sha256"],
        "price_source_path": SOURCE_MANIFEST,
        "reviewed_at": review["reviewed_at"],
        "benchmark": "CSI300 / 000300.SH",
        "reviewed_price_cutoff": review["price_cutoff"],
        "reviewed_price_rows": review["price_rows"],
        "event_families": [
            {"id": key, "source": row["source"], "readiness": row["readiness"],
             "historical_pit_verified": consistent and row.get("pit_verified") is True}
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
             "other_observations": row["other"]["observations"],
             "latest_mature_observation": row["eligible_observation_end"],
             "latest_label_end": row["label_end_end"],
             "immature_observations": row["insufficient_future_bars"]["count"]}
            for row in results
        ] if consistent else [],
        "evidence": [{"path": path, "sha256": digest} for path, digest in evidence.items()],
        "protocol_path": PROTOCOL,
    }
