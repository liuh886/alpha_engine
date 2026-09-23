from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def test_qlib_recorder_round_trip_with_sqlite_backend(tmp_path: Path) -> None:
    """Prove pyqlib's recorder contract against the resolved MLflow major version."""
    script = textwrap.dedent(
        r"""
        import sys
        from pathlib import Path

        import mlflow
        from qlib.workflow import QlibRecorder, R
        from qlib.workflow.expm import MLflowExpManager

        root = Path(sys.argv[1]).resolve()
        db_path = root / "mlflow.db"
        tracking_uri = f"sqlite:///{db_path.as_posix()}"
        experiment_name = "workflow_mlflow_compat_smoke"
        recorder_name = "round-trip"

        R.register(
            QlibRecorder(
                MLflowExpManager(
                    uri=tracking_uri,
                    default_exp_name=experiment_name,
                )
            )
        )

        with R.start(
            experiment_name=experiment_name,
            recorder_name=recorder_name,
        ):
            R.log_params(alpha_engine_compat="ok")
            R.log_metrics(compat_metric=1.25)
            R.save_objects(**{"payload.pkl": {"status": "ok"}})
            recorder_id = R.get_recorder().id

        experiments = R.list_experiments()
        assert experiment_name in experiments

        recorders = R.list_recorders(experiment_name=experiment_name)
        assert recorder_id in recorders

        recorder = R.get_recorder(
            recorder_id=recorder_id,
            experiment_name=experiment_name,
        )
        assert recorder.list_params()["alpha_engine_compat"] == "ok"
        assert recorder.list_metrics()["compat_metric"] == 1.25
        assert recorder.load_object("payload.pkl") == {"status": "ok"}

        records = R.search_records([recorder.experiment_id])
        assert any(run.info.run_id == recorder_id for run in records)

        assert db_path.exists()
        assert int(mlflow.__version__.split(".", maxsplit=1)[0]) >= 3
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, (
        "qlib.workflow.R / MLflow SQLite compatibility smoke failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
