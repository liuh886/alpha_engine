from __future__ import annotations

from pathlib import Path

import scripts.run_formal_strategy_refresh as runner
from src.artifacts.formal_refresh import load_object, write_object


def _us_task(*, formal: bool, mtm: bool) -> dict[str, object]:
    return {
        "strategy_id": "us_x",
        "model_family_id": "us_ranker",
        "model_version_id": "us_x1_3",
        "model_kind": "cross_sectional_ranker",
        "market": "us",
        "planned_provider_cutoff": "2026-08-12",
        "publication_input": "native_bundle_v2",
        "formal_refresh_required": formal,
        "mtm_refresh_required": mtm,
    }


def test_us_daily_mtm_fast_path_never_runs_historical_preview_builder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path.resolve()
    provider_root = root / "provider-root"
    formal_root = root / "formal"
    current_preview = root / "preview"
    result_root = root / "result"
    provider_root.mkdir()
    formal_root.mkdir()
    current_preview.mkdir()
    result_root.mkdir()

    monkeypatch.setattr(
        runner,
        "_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("historical builder must not run on MTM-only refresh")
        ),
    )
    monkeypatch.setattr(runner, "_current_preview_bundle_id", lambda *_args: "current-bundle")

    def materialize(*, target: Path, **_kwargs):
        payload = {
            "model_id": "us_x1_3",
            "evidence_cutoff": "2026-08-11",
            "freshness": {"status": "current"},
            "report": [{"date": "2026-07-16", "holding_end_date": "2026-07-30"}],
            "positions": [{"date": "2026-07-30", "instrument": "A", "weight": 1.0}],
        }
        write_object(target, payload)
        return payload

    def attach(*, package_path: Path, cutoff: str, **_kwargs):
        payload = load_object(package_path)
        payload["evidence_cutoff"] = cutoff
        payload["freshness"] = {
            "status": "current",
            "latest_mtm_date": cutoff,
        }
        write_object(package_path, payload)
        return {"as_of": cutoff}

    monkeypatch.setattr(runner, "_materialize_refresh_state", materialize)
    monkeypatch.setattr(runner, "attach_ranker_provisional_mtm", attach)
    monkeypatch.setattr(runner, "_seal_preview", lambda **_kwargs: ("catalog-sha", "candidate-bundle"))

    receipt = runner._run_us(
        root=root,
        task=_us_task(formal=False, mtm=True),
        provider_root=provider_root,
        formal_v2_root=formal_root,
        current_preview_root=current_preview,
        result_root=result_root,
        generated_at="2026-08-12T23:00:00Z",
    )

    assert receipt["execution_status"] == "refreshed"
    assert receipt["candidate_evidence_cutoff"] == "2026-08-12"
    assert receipt["performance_observation_end"] == "2026-08-12"
    assert receipt["replay_verdict"] == "ledger_mtm_projection_no_historical_rebuild"


def test_settled_report_ignores_provisional_observations() -> None:
    assert runner._settled_report(
        {
            "report": [
                {"date": "2026-07-30", "account": 1.1},
                {
                    "date": "2026-08-12",
                    "account": 1.2,
                    "provisional_mtm": True,
                    "settlement_status": "provisional_mtm",
                },
            ]
        }
    ) == [{"date": "2026-07-30", "account": 1.1}]
