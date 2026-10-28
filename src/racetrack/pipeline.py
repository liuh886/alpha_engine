"""Racetrack daily self-maintaining publishing pipeline and atomic landing.

Implements multi-market automated pipeline execution, dual benchmark simulations,
registered runner evaluation, season scoring, privacy scanning, bit-level deterministic
manifest signing, and fail-closed atomic staging and promotion.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
import uuid

from src.racetrack.contracts import (
    EngineConfig,
    Scoreboard,
    assert_privacy_clean,
)
from src.racetrack.matrix import load_price_matrix
from src.racetrack.pool_index import generate_equal_weight_pool_index
from src.racetrack.runner import RunnerRegistry, validate_runner_thesis
from src.racetrack.scoring import (
    evaluate_race_season,
    generate_benchmark_simulation,
)

MARKET_SPECS: dict[str, dict[str, str]] = {
    "us": {
        "candidate_pool": "us_selected_equities_v2",
        "benchmark": "QQQ",
        "calendar": "XNYS",
        "internal_benchmark_id": "benchmark_us_selected_equities_v2_ew",
        "macro_label": "QQQ",
        "pool_label": "US87",
    },
    "cn": {
        "candidate_pool": "cn_selected_equities_v3",
        "benchmark": "000300",
        "calendar": "XSHG",
        "internal_benchmark_id": "benchmark_cn_selected_equities_v3_ew",
        "macro_label": "CSI300",
        "pool_label": "CN130",
    },
}


@dataclass(frozen=True)
class PipelineResult:
    """Immutable result contract of racetrack publishing pipeline execution."""

    manifest_path: Path
    market: str
    as_of_cutoff: str
    as_of_session: str
    season_id: str
    pool_id: str
    benchmark_symbol: str
    manifest_dict: dict[str, Any]
    manifest_sha256: str
    latest_scoreboard_path: Path
    archive_scoreboard_path: Path
    scoreboard: Scoreboard
    matrix_sha256: str
    runner_count: int

    def __fspath__(self) -> str:
        """Allow PipelineResult to be passed directly to file/path operations."""
        return str(self.manifest_path)


def compute_file_sha256(path: Path) -> str:
    """Compute standard SHA-256 hex digest of file on disk."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_code_sha256(root_path: Path) -> str:
    """Compute deterministic SHA-256 fingerprint over all racetrack source modules."""
    racetrack_dir = root_path / "src" / "racetrack"
    h = hashlib.sha256()
    if racetrack_dir.exists():
        for py_file in sorted(racetrack_dir.glob("*.py")):
            h.update(py_file.name.encode("utf-8"))
            h.update(py_file.read_bytes())
        return h.hexdigest()
    return "0" * 64


def get_git_commit_sha(root_path: Path) -> str:
    """Resolve HEAD for normal checkouts, packed refs and linked worktrees."""
    try:
        return subprocess.run(
            ["git", "-C", str(root_path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "uncommitted_research_working_tree"


def publish_racetrack_projection(
    market: str = "us",
    as_of_cutoff: str | None = None,
    output_dir: Path | None = None,
    registry: RunnerRegistry | None = None,
    runners_registry: RunnerRegistry | None = None,
    config: EngineConfig = EngineConfig(),
    start_date: str = "2024-01-01",
    repo_root: Path | None = None,
    root_path: Path | None = None,
    season_id: str | None = None,
    generated_at_utc: str | None = None,
) -> PipelineResult:
    """Execute end-to-end Racetrack publication pipeline with atomic landing and fail-closed integrity.

    Workflow:
        1. Resolve market universe, calendar, and reference benchmark configurations.
        2. Validate PIT cutoff and load PriceMatrix P(t, s).
        3. Generate internal declared equal-weight pool benchmark simulation.
        4. Generate external macro benchmark simulation (QQQ / CSI 300).
        5. Batch evaluate registered runners with thesis verification and whitelist assertion.
        6. Compute cross-sectional rankings, rolling returns, and season scoreboard.
        7. Enforce multi-layer privacy boundary (assert zero personal account fields).
        8. Atomic landing: write to .staging_{uuid}/, sign SHA-256 manifests, promote atomically.
        9. Fail-Closed: if any step raises exception, purge staging, leaving production untouched.

    Args:
        market: Target market identifier ('us' or 'cn').
        as_of_cutoff: Historical point-in-time cutoff date (YYYY-MM-DD). If None, inferred from catalog.json.
        output_dir: Destination directory for published artifacts.
        registry: RunnerRegistry containing admitted runner contracts.
        runners_registry: Alias for registry.
        config: Portfolio and friction simulation configuration.
        start_date: Backtest start session date.
        repo_root: Repository root path.
        root_path: Alias for repo_root.
        season_id: Custom season identifier. If None, derived from market and session.
        generated_at_utc: Deterministic generation timestamp (defaults to session midnight UTC).

    Returns:
        PipelineResult containing paths, metadata, hashes, and Scoreboard contract.

    Raises:
        CalendarSessionError: If trading sessions cannot be resolved.
        PITViolationError: If requested date extends beyond PIT cutoff.
        PrivacyViolationError: If sensitive personal account fields are detected.
        DataQualificationError: If asset is not registered in evidence catalog.
    """
    market_lower = market.lower()
    if market_lower not in MARKET_SPECS:
        raise ValueError(
            f"Unsupported market '{market}'. Must be one of {list(MARKET_SPECS.keys())}"
        )

    spec = MARKET_SPECS[market_lower]
    candidate_pool = spec["candidate_pool"]
    benchmark_symbol = spec["benchmark"]
    internal_benchmark_id = spec["internal_benchmark_id"]

    root = Path(repo_root or root_path or Path.cwd()).resolve()

    # 1. Resolve cutoff date from market catalog if not explicitly provided
    catalog_path = root / "data" / "research" / "market_evidence" / market_lower / "catalog.json"
    if as_of_cutoff is None:
        if not catalog_path.exists():
            raise FileNotFoundError(f"Market evidence catalog not found: {catalog_path}")
        cat_data = json.loads(catalog_path.read_text(encoding="utf-8"))
        as_of_cutoff = str(cat_data.get("cutoff", ""))
        if not as_of_cutoff:
            raise ValueError(f"No cutoff field found in catalog '{catalog_path}'")

    # 2. Resolve destination directory
    out_dir = Path(
        output_dir or (root / "data" / "racetrack" / "projections" / market_lower)
    ).resolve()

    # 3. Step 1: Load PriceMatrix P(t, s)
    matrix = load_price_matrix(
        market=market_lower,
        pool_id=candidate_pool,
        start_date=start_date,
        end_date=as_of_cutoff,
        as_of_cutoff=as_of_cutoff,
        root_path=root,
    )
    as_of_session = matrix.end_session

    # 4. Step 2: Generate internal declared pool index simulation
    pool_sim = generate_equal_weight_pool_index(
        matrix=matrix,
        pool_id=candidate_pool,
        config=config,
    )

    # 5. Step 3: Generate external macro benchmark simulation
    macro_sim = generate_benchmark_simulation(
        matrix=matrix,
        symbol=benchmark_symbol,
        config=config,
    )

    # 6. Step 4: Batch evaluate registered runners (if provided)
    active_registry = registry if registry is not None else runners_registry
    simulation_results: dict[str, Any] = {}
    runners_map: dict[str, Any] = {}

    if active_registry is not None and active_registry.list_runners():
        for runner in active_registry.list_runners():
            validate_runner_thesis(runner.thesis)
            # Cross-market isolation check
            if runner.pool_id != candidate_pool:
                raise ValueError(
                    f"Runner '{runner.runner_id}' declared pool '{runner.pool_id}' "
                    f"which does not match target market pool '{candidate_pool}'"
                )
        simulation_results = active_registry.evaluate_all(matrix=matrix, config=config)
        runners_map = {r.runner_id: r for r in active_registry.list_runners()}

    # 7. Step 5: Settle season scoring & generate scoreboard
    if season_id is None:
        resolved_season_id = f"season_{market_lower}_{as_of_session[:7].replace('-', '_')}"
    else:
        resolved_season_id = season_id

    scoreboard = evaluate_race_season(
        runners=runners_map,
        simulation_results=simulation_results,
        qqq_simulation=macro_sim,
        pool_simulation=pool_sim,
        season_id=resolved_season_id,
        pool_id=candidate_pool,
        benchmark_symbol=benchmark_symbol,
    )

    # 8. Step 6: Security and Privacy Guard recursive scan
    # Inspect all runners, simulations, scoreboard entries and raw dicts
    for r in runners_map.values():
        if hasattr(r, "__dict__"):
            assert_privacy_clean(r.__dict__)
    for sim in simulation_results.values():
        if hasattr(sim, "to_dict"):
            assert_privacy_clean(sim.to_dict())
        if hasattr(sim, "__dict__"):
            assert_privacy_clean(sim.__dict__)

    scoreboard_dict = scoreboard.to_dict()
    assert_privacy_clean(scoreboard_dict)

    # 9. Step 7: Atomic landing with staging and fail-closed promotion
    # The current manifest is the only mutable publication pointer. Every
    # referenced release is immutable, so readers never observe mixed artifacts.
    identity = {
        "scoreboard": scoreboard_dict,
        "matrix": matrix.matrix_sha256,
        "catalog": matrix.catalog_sha256,
        "cutoff": as_of_cutoff,
        "code": get_code_sha256(root),
        "git": get_git_commit_sha(root),
        "config": config.__dict__,
        "generated_at": generated_at_utc,
    }
    governed_configs = {
        "pool": root / "configs" / "research_universes" / f"{candidate_pool}.yaml",
        "selected_pool_registry": root / "configs" / "pools" / "selected_pool_registry_v1.yaml",
        "reference_registry": root / "configs" / "pools" / "reference_instrument_registry_v1.yaml",
    }
    config_hashes = {name: compute_file_sha256(path) for name, path in governed_configs.items()}
    identity["governed_config_hashes"] = config_hashes
    identity["data_qualification"] = matrix.data_qualification
    release_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()
    release_relative = Path("versions") / release_id
    release_dir = out_dir / release_relative
    staging_dir = out_dir / f".staging_{uuid.uuid4().hex}"
    staging_archive = staging_dir / "archive"

    try:
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging_archive.mkdir(parents=True, exist_ok=True)

        # Write scoreboard archive snapshot
        archive_file = staging_archive / f"scoreboard_{as_of_session}.json"
        scoreboard_json_str = scoreboard.to_json(indent=2) + "\n"
        archive_file.write_text(scoreboard_json_str, encoding="utf-8")

        # Write scoreboard latest projection
        latest_file = staging_dir / "scoreboard_latest.json"
        latest_file.write_text(scoreboard_json_str, encoding="utf-8")

        # Compute cryptographic fingerprints
        archive_sha256 = compute_file_sha256(archive_file)
        archive_size = archive_file.stat().st_size
        latest_sha256 = compute_file_sha256(latest_file)
        latest_size = latest_file.stat().st_size

        code_sha256 = get_code_sha256(root)
        git_sha = get_git_commit_sha(root)
        gen_time = generated_at_utc or f"{as_of_session}T00:00:00Z"

        manifest_dict = {
            "schema_version": "1.0",
            "pipeline_version": "1.1.0",
            "release_id": release_id,
            "status": scoreboard.status,
            "data_qualification": matrix.data_qualification,
            "engine_config": config.__dict__,
            "governed_config_hashes": config_hashes,
            "generated_at_utc": gen_time,
            "market": market_lower,
            "as_of_session": as_of_session,
            "as_of_cutoff": as_of_cutoff,
            "last_session": as_of_session,
            "pool_id": candidate_pool,
            "benchmark_symbol": benchmark_symbol,
            "internal_benchmark_id": internal_benchmark_id,
            "matrix_sha256": matrix.matrix_sha256,
            "catalog_sha256": matrix.catalog_sha256,
            "code_sha256": code_sha256,
            "git_commit_sha": git_sha,
            "runner_count": len(runners_map),
            "season_id": resolved_season_id,
            "research_only": True,
            "trade_ready": False,
            "artifacts": {
                "scoreboard_archive": {
                    "path": (
                        release_relative / "archive" / f"scoreboard_{as_of_session}.json"
                    ).as_posix(),
                    "sha256": archive_sha256,
                    "size_bytes": archive_size,
                },
                "scoreboard_latest": {
                    "path": (release_relative / "scoreboard_latest.json").as_posix(),
                    "sha256": latest_sha256,
                    "size_bytes": latest_size,
                },
            },
        }

        # Privacy verification over manifest metadata
        assert_privacy_clean(manifest_dict)

        manifest_file = staging_dir / "manifest.json"
        manifest_json_str = (
            json.dumps(manifest_dict, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        manifest_file.write_text(manifest_json_str, encoding="utf-8")
        manifest_sha256 = compute_file_sha256(manifest_file)

        # First land the complete immutable vintage. An existing vintage must
        # match byte-for-byte; a changed same-session run gets another identity.
        release_dir.parent.mkdir(parents=True, exist_ok=True)
        if release_dir.exists():
            for name in (
                "manifest.json",
                "scoreboard_latest.json",
                f"archive/scoreboard_{as_of_session}.json",
            ):
                if (release_dir / name).read_bytes() != (staging_dir / name).read_bytes():
                    raise ValueError("Existing release differs from its content identity")
        else:
            os.rename(staging_dir, release_dir)
        target_archive_file = release_dir / "archive" / f"scoreboard_{as_of_session}.json"
        target_latest_file = release_dir / "scoreboard_latest.json"
        target_manifest_file = out_dir / "manifest.json"
        pointer = out_dir / f".manifest_{uuid.uuid4().hex}.tmp"
        try:
            with pointer.open("wb") as handle:
                handle.write(manifest_json_str.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            # Single atomic replace: a failure leaves the previous release
            # readable; an unreferenced complete vintage is harmless to retain.
            os.replace(pointer, target_manifest_file)
        finally:
            pointer.unlink(missing_ok=True)

        return PipelineResult(
            manifest_path=target_manifest_file,
            market=market_lower,
            as_of_cutoff=as_of_cutoff,
            as_of_session=as_of_session,
            season_id=resolved_season_id,
            pool_id=candidate_pool,
            benchmark_symbol=benchmark_symbol,
            manifest_dict=manifest_dict,
            manifest_sha256=manifest_sha256,
            latest_scoreboard_path=target_latest_file,
            archive_scoreboard_path=target_archive_file,
            scoreboard=scoreboard,
            matrix_sha256=matrix.matrix_sha256,
            runner_count=len(runners_map),
        )

    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def render_racetrack_scoreboard(
    input_dir: Path,
    format_type: str = "markdown",
    market: str = "us",
) -> str:
    """Render Racetrack scoreboard projection into friendly terminal format.

    Args:
        input_dir: Path to directory containing scoreboard_latest.json.
        format_type: Output formatting ('markdown', 'table', or 'json').
        market: Market identifier for header rendering.

    Returns:
        Formatted string representation ready for terminal printing.
    """
    root = Path(input_dir).resolve()
    manifest_file = root / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    expected = MARKET_SPECS.get(market.lower())
    if expected is None or manifest.get("market") != market.lower():
        raise ValueError("Projection market does not match requested market")
    if (
        manifest.get("schema_version") != "1.0"
        or manifest.get("pipeline_version") != "1.1.0"
        or manifest.get("pool_id") != expected["candidate_pool"]
        or manifest.get("research_only") is not True
        or manifest.get("trade_ready") is not False
    ):
        raise ValueError("Unrecognized projection identity or research boundary")
    for artifact in manifest["artifacts"].values():
        path = (root / artifact["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Projection artifact is missing or escapes the release root")
        if (
            compute_file_sha256(path) != artifact["sha256"]
            or path.stat().st_size != artifact["size_bytes"]
        ):
            raise ValueError("Projection artifact hash/size mismatch")
    latest_file = root / manifest["artifacts"]["scoreboard_latest"]["path"]
    scoreboard = Scoreboard.from_json(latest_file.read_text(encoding="utf-8"))
    if (
        scoreboard.pool_id != manifest["pool_id"]
        or scoreboard.benchmark_symbol != manifest["benchmark_symbol"]
        or scoreboard.as_of_session != manifest["as_of_session"]
        or scoreboard.season_id != manifest["season_id"]
    ):
        raise ValueError("Scoreboard identity does not match the manifest")

    if format_type.lower() == "json":
        return scoreboard.to_json(indent=2)

    spec = MARKET_SPECS.get(
        market.lower(),
        {"macro_label": "Benchmark", "pool_label": "Pool"},
    )
    macro_lbl = spec["macro_label"]
    pool_lbl = spec["pool_label"]

    def _fmt_pct(val: float | None) -> str:
        if val is None:
            return "N/A"
        sign = "+" if val > 0 else ""
        return f"{sign}{val * 100:.1f}%"

    def _fmt_ratio(val: float | None) -> str:
        if val is None:
            return "N/A"
        return f"{val:.2f}"

    if format_type.lower() == "table":
        lines = [
            f"=== RACETRACK SCOREBOARD [{market.upper()}] ===",
            f"As of Session: {scoreboard.as_of_session} | Season: {scoreboard.season_id} | Pool: {scoreboard.pool_id}",
            "-" * 96,
            f"{'Rank':<5}{'Runner ID':<22}{'Ver':<7}{'Pts':<6}{'1M Ret':<10}{'3M Ret':<10}{'1Y Ret':<10}{'Sharpe':<8}{'MaxDD':<9}{'Persistence'}",
            "-" * 96,
        ]
        if not scoreboard.entries:
            lines.append("  (No registered runners - benchmark only)")
        else:
            for e in scoreboard.entries:
                lines.append(
                    f"{e.current_rank:<5}{e.runner_id:<22}{e.runner_version:<7}{e.season_points:<6}"
                    f"{_fmt_pct(e.return_1m):<10}{_fmt_pct(e.return_3m):<10}{_fmt_pct(e.return_1y):<10}"
                    f"{_fmt_ratio(e.sharpe_ratio):<8}{_fmt_pct(e.max_drawdown):<9}{e.persistence_ratio * 100:.1f}%"
                )
        lines.append("-" * 96)
        lines.append(
            "Note: Periods include partial calendar months; points are provisional until full-window review. Adjusted-price research returns; see manifest for friction and PIT qualification. research_only=true, trade_ready=false."
        )
        return "\n".join(lines)

    # Markdown format
    md_lines = [
        f"# Racetrack Competitive Scoreboard ({market.upper()} Market)",
        f"**As of Session**: {scoreboard.as_of_session} | **Season**: {scoreboard.season_id} | "
        f"**Pool**: {scoreboard.pool_id} | **Benchmark**: {scoreboard.benchmark_symbol} | **Status**: {scoreboard.status}\n",
        f"| Rank | Runner ID | Ver | Pts | 1M Ret | 3M Ret | 1Y Ret | vs {macro_lbl} | vs {pool_lbl} | MaxDD | Sharpe | Persistence | Thesis Summary |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]
    if not scoreboard.entries:
        md_lines.append(
            "| - | (No registered runners - benchmark only) | - | - | - | - | - | - | - | - | - | - | - |"
        )
    else:
        for e in scoreboard.entries:
            summary = e.thesis_summary.replace("|", "/")
            md_lines.append(
                f"| **{e.current_rank}** | {e.runner_id} | {e.runner_version} | **{e.season_points}** | "
                f"{_fmt_pct(e.return_1m)} | {_fmt_pct(e.return_3m)} | {_fmt_pct(e.return_1y)} | "
                f"{_fmt_pct(e.excess_vs_qqq)} | {_fmt_pct(e.excess_vs_pool)} | "
                f"{_fmt_pct(e.max_drawdown)} | {_fmt_ratio(e.sharpe_ratio)} | "
                f"{e.persistence_ratio * 100:.1f}% | {summary} |"
            )
    md_lines.append("")
    md_lines.append(
        "*Note: Periods include partial calendar months; points are provisional until full-window review. Returns use adjusted prices and manifest-bound friction. research_only=true, trade_ready=false.*"
    )
    return "\n".join(md_lines)
