"""Certify frozen CN x1.1 regime-gated evidence with fallback-aware evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.run_cn_x1_1_regime_gated import run as run_original_evidence
from src.research.cn_x1_1_fallback_aware_certification import (
    FROZEN_ECONOMIC_HASHES,
    build_certified_decision,
    verify_frozen_economic_identity,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def certification_report(
    decision: dict[str, Any],
    evaluation: pd.DataFrame,
    observed_hashes: dict[str, str],
) -> str:
    historical = evaluation.loc[
        evaluation["evaluation"] == "historical_2022H2_2025H2"
    ].iloc[0]
    reporting = evaluation.loc[evaluation["evaluation"] == "reporting_2026"].iloc[0]
    lines = [
        "# CN x1.1 Candidate A — Regime-Gated Sector Breadth",
        "",
        f"**Decision:** `{decision['decision']}`",
        "",
        "## 授权结果",
        "",
        f"- Candidate authorized: {decision['candidate_authorized']}",
        f"- Candidate name: `{decision['candidate_name']}`",
        "- Model rules changed: false",
        "- Economic evidence changed: false",
        "- Automatic production promotion: false",
        "- `trade_ready=false`；本次仅授权研究候选，不自动替换生产基准。",
        "",
        "## 冻结模型",
        "",
        "- Risk-on：CN x1.0 R0分数 → 行业Top3广度 → 四行业 → 每行业Top1 → 四股等权。",
        "- Risk-off：100% CSI300 fallback。",
        "- 状态门：CSI300高于MA200、60日动量为正、CN130广度≥50%，三项两票通过。",
        "- 十个交易日再平衡；延迟一个交易日执行；20bps/换手。",
        "",
        "## 核心证据",
        "",
        f"- 2022H2—2025H2相对超额：{historical['relative_excess']:.2%}",
        f"- 历史最大回撤：{historical['max_drawdown']:.2%}",
        f"- 正超额半年：{int(historical['positive_excess_windows'])}/7",
        f"- Risk-on主动胜率：{historical['risk_on_active_hit_rate']:.1%}",
        f"- Risk-on占比：{historical['risk_on_share']:.1%}",
        f"- Risk-on相对超额：{historical['risk_on_relative_excess']:.2%}",
        f"- Risk-off相对超额：{historical['risk_off_relative_excess']:.2%}，与显式成本拖累一致。",
        f"- 2026报告期相对超额：{reporting['relative_excess']:.2%}",
        "",
        "## 评价合同修正",
        "",
        "原合同把Risk-off的CSI300 fallback也要求逐期跑赢CSI300；扣除状态切换成本后，该要求在定义上不可满足。最终合同只将50%胜率门应用于Risk-on主动袖套，同时继续要求Risk-off表现不劣于显式成本拖累。其它门槛均未改变。",
        "",
        "## 冻结经济证据身份",
        "",
    ]
    for filename in sorted(observed_hashes):
        lines.append(f"- `{filename}`: `{observed_hashes[filename]}`")
    lines.extend(["", "## 候选边界", ""])
    for gate, passed in decision["gates"].items():
        lines.append(f"- `{gate}`: {'PASS' if passed else 'FAIL'}")
    lines.extend(
        [
            "",
            "本候选仍基于固定CN130精选池，存在静态池生存者偏差。正式升级、前端接入和生产交易信号发布需另行明确决定。",
            "",
        ]
    )
    return "\n".join(lines)


def certify(
    root: Path,
    provider_dir: Path,
    ledger_dirs: list[Path],
    output_dir: Path,
) -> dict[str, Any]:
    original_decision = run_original_evidence(
        root,
        provider_dir,
        ledger_dirs,
        output_dir,
    )
    observed_hashes = verify_frozen_economic_identity(output_dir)
    evaluation = pd.read_csv(output_dir / "evaluation_summary.csv")
    historical = evaluation.loc[
        evaluation["evaluation"] == "historical_2022H2_2025H2"
    ]
    if len(historical) != 1:
        raise ValueError("expected one historical evaluation row")
    active_hit_rate = float(historical.iloc[0]["risk_on_active_hit_rate"])
    decision = build_certified_decision(
        original_decision,
        active_hit_rate=active_hit_rate,
        frozen_identity_verified=True,
    )
    write_json(output_dir / "decision.json", decision)
    write_json(
        output_dir / "evaluation_contract.json",
        {
            "schema_version": "benchmark_fallback_aware_v1",
            "source_issue": 575,
            "source_workflow_run": 31021964502,
            "source_artifact": 8936993760,
            "source_artifact_digest": "sha256:43c3caccb6535270a61323bd1b8e02df58b881617cdfd6f162de9b17c09a7c14",
            "frozen_economic_hashes": FROZEN_ECONOMIC_HASHES,
            "replaced_gate": decision["replaced_gate"],
            "replacement_gate": decision["replacement_gate"],
            "model_rules_changed": False,
            "economic_evidence_changed": False,
        },
    )
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(
        {
            "schema_version": "cn_x1_1_fallback_aware_certification_v1",
            "decision": decision["decision"],
            "candidate_authorized": decision["candidate_authorized"],
            "evaluation_contract": decision["evaluation_contract"],
            "frozen_economic_identity_verified": True,
            "trade_ready": False,
        }
    )
    write_json(output_dir / "manifest.json", manifest)
    (output_dir / "report.md").write_text(
        certification_report(decision, evaluation, observed_hashes),
        encoding="utf-8",
    )
    files = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "evidence_manifest.json"
    )
    write_json(
        output_dir / "evidence_manifest.json",
        {
            "schema_version": "1.0.0",
            "experiment_id": "cn_x1_1_regime_gated_sector_breadth_v1",
            "certification_id": "fallback_aware_v1",
            "decision": decision,
            "files": [
                {
                    "path": path.name,
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                }
                for path in files
            ],
        },
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return decision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument(
        "--ledger-dir", dest="ledger_dirs", type=Path, action="append", required=True
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    certify(
        args.root.resolve(),
        args.provider_dir.resolve(),
        [path.resolve() for path in args.ledger_dirs],
        args.output_dir.resolve(),
    )


if __name__ == "__main__":
    main()
