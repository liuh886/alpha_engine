import re
from pathlib import Path

import yaml


PURGE_LIST = Path("configs/data_quality/history_purge_paths_v1.txt")
US_SELECTED = Path("configs/research_universes/us_selected_equities_v2.yaml")
CN_SELECTED = Path("configs/research_universes/cn_selected_equities_v3.yaml")
WORKFLOW = Path(".github/workflows/purge-deleted-market-data-history.yml")
USER_RETAINED = {
    "000338",
    "000895",
    "002202",
    "300017",
    "300133",
    "600184",
    "600875",
}
OTHER_PROTECTED = {"600837", "601989", "TIGO", "TYGO", "SNDK"}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_history_purge_contract_is_exact_and_safe() -> None:
    lines = PURGE_LIST.read_text(encoding="utf-8").splitlines()
    paths = [line.strip() for line in lines if line.strip()]
    pattern = re.compile(r"data/csv_clean/[A-Za-z0-9]+\.csv")

    assert len(paths) == len(set(paths)) == 138
    assert all(pattern.fullmatch(path) for path in paths)

    purge_symbols = {Path(path).stem for path in paths}
    us_symbols = set(_load(US_SELECTED)["symbols"])
    cn_symbols = set(_load(CN_SELECTED)["symbols"])

    assert purge_symbols.isdisjoint(us_symbols)
    assert purge_symbols.isdisjoint(cn_symbols)
    assert USER_RETAINED.isdisjoint(purge_symbols)
    assert OTHER_PROTECTED.isdisjoint(purge_symbols)

    for path in paths:
        assert not Path(path).exists(), path


def test_completed_one_shot_history_purge_workflow_is_retired() -> None:
    assert not WORKFLOW.exists()
    assert PURGE_LIST.exists()
