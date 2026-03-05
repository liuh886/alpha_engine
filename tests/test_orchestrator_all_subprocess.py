import sys

import src.orchestrator as orchestrator


def test_orchestrator_market_all_runs_via_subprocess(monkeypatch):
    calls: list[list[str]] = []

    def fail_compile(*_args, **_kwargs):
        raise AssertionError("build_compile_cmd should not be called in parent 'all' run")

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(orchestrator, "build_compile_cmd", fail_compile)
    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)

    orchestrator.Orchestrator().run(
        market="all",
        model_type="lgbm",
        profile="configs/strategy_profile.json",
        tag="TEST_TAG",
    )

    assert len(calls) == 2
    assert calls[0][:4] == [sys.executable, "-m", "src.orchestrator", "run"]
    assert calls[1][:4] == [sys.executable, "-m", "src.orchestrator", "run"]

    assert calls[0][calls[0].index("--market") + 1] == "cn"
    assert calls[1][calls[1].index("--market") + 1] == "us"
