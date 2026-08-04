from __future__ import annotations

import sys
import traceback
from pathlib import Path

import scripts.run_qqqi_v4_2_donor_state2_sgov_tqqq as runner
from src.research.v4_2_donor_state2_sgov_tqqq_runtime_coverage import (
    run_donor_state2_sgov_tqqq,
)

runner.run_donor_state2_sgov_tqqq = run_donor_state2_sgov_tqqq
DEFAULT_OUTPUT = runner.DEFAULT_OUTPUT


def _output_dir(argv: list[str]) -> Path:
    try:
        position = argv.index("--output-dir")
    except ValueError:
        return DEFAULT_OUTPUT
    if position + 1 >= len(argv):
        return DEFAULT_OUTPUT
    return Path(argv[position + 1])


if __name__ == "__main__":
    try:
        raise SystemExit(runner.main())
    except SystemExit:
        raise
    except Exception:
        output = _output_dir(sys.argv[1:])
        output.mkdir(parents=True, exist_ok=True)
        (output / "failure_traceback.txt").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        raise
