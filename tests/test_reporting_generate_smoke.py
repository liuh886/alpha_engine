import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_reporting_generate_imports_pickle():
    import src.reporting.generate as mod

    assert hasattr(mod, "pickle")

