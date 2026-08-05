"""Normalize CNINFO title markup and repair the Phase 2 overlap audit."""

from __future__ import annotations

import py_compile
from pathlib import Path

ADAPTER = Path("src/data/company_events/ashare_primary_announcements.py")
BUILDER = Path("scripts/data/build_cn130_pit_event_families_phase2.py")
TEST = Path("tests/test_ashare_primary_company_events.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one target, found {count}")
    return text.replace(old, new, 1)


def patch_adapter() -> None:
    text = ADAPTER.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "import hashlib\nimport json\nimport re\n",
        "import hashlib\nimport json\nimport re\nfrom html import unescape\n",
        "html import",
    )
    text = replace_once(
        text,
        '''def _canonical_title(title: str) -> str:\n    text = re.sub(r"\\s+", "", str(title or ""))\n    for token in _SUMMARY_TOKENS:\n        text = text.replace(token, "")\n    return re.sub(r"[：:，,。．（）()【】\\[\\]《》<>·—_-]", "", text)\n''',
        '''def _clean_title(title: str) -> str:\n    text = unescape(re.sub(r"<[^>]+>", "", str(title or "")))\n    return re.sub(r"\\s+", "", text).strip()\n\n\ndef _canonical_title(title: str) -> str:\n    text = _clean_title(title)\n    for token in _SUMMARY_TOKENS:\n        text = text.replace(token, "")\n    return re.sub(r"[：:，,。．（）()【】\\[\\]《》<>·—_-]", "", text)\n''',
        "title cleaner",
    )
    start = text.index("def classify_buyback_title")
    end = text.index("\n\ndef classify_restricted_unlock_title", start)
    buyback = '''def classify_buyback_title(title: str) -> str | None:\n    """Classify a primary buyback announcement without current-state backfill."""\n\n    text = _clean_title(title)\n    if "回购" not in text:\n        return None\n    unrelated = (\n        "限制性股票",\n        "股票期权",\n        "业绩补偿",\n        "承诺回购",\n        "质押式回购",\n        "逆回购",\n        "债券回购",\n        "回购交易",\n        "法律意见",\n        "核查意见",\n    )\n    if any(token in text for token in unrelated):\n        return None\n    if any(\n        token in text\n        for token in ("回购完成", "实施完成", "实施完毕", "实施结果", "结果暨股份变动", "期限届满")\n    ):\n        return "completion"\n    if "首次" in text and "回购" in text:\n        return "first_execution"\n    if "进展" in text or "累计回购" in text or "比例达到" in text:\n        return "progress"\n    if "股东大会" in text and any(token in text for token in ("通过", "决议", "审议")):\n        return "approval"\n    if any(token in text for token in ("方案", "报告书", "提议回购", "董事会提议")):\n        return "plan"\n    return None\n'''
    text = text[:start] + buyback + text[end:]
    start = text.index("def classify_restricted_unlock_title")
    end = text.index("\n\ndef _source_hash", start)
    unlock = '''def classify_restricted_unlock_title(title: str) -> str | None:\n    """Retain primary documents that explicitly open restricted shares for trading."""\n\n    text = _clean_title(title)\n    if any(token in text for token in ("核查意见", "法律意见书", "律师事务所")):\n        return None\n    explicit_listing = "上市流通" in text and any(\n        token in text\n        for token in ("限售", "解除限售", "首次公开发行前已发行股份", "首次公开发行部分股份")\n    )\n    if explicit_listing:\n        return "scheduled"\n    if "限售股份解除限售" in text:\n        return "scheduled"\n    return None\n'''
    text = text[:start] + unlock + text[end:]
    text = replace_once(
        text,
        '        title = str(_first(raw, ("公告标题", "title")) or "").strip()\n',
        '        title = _clean_title(_first(raw, ("公告标题", "title")) or "")\n',
        "adapter title normalization",
    )
    ADAPTER.write_text(text, encoding="utf-8")
    py_compile.compile(str(ADAPTER), doraise=True)


def patch_builder() -> None:
    text = BUILDER.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    overlap_matrix,\n",
        "",
        "remove inherited overlap import",
    )
    anchor = 'FAMILIES = ("buyback", "restricted_unlock")\n\n\n'
    function = '''FAMILIES = ("buyback", "restricted_unlock")\n\n\ndef phase2_overlap_matrix(events: pd.DataFrame) -> pd.DataFrame:\n    """Measure same-symbol/date overlap only across the Phase 2 families."""\n\n    keys: dict[str, set[tuple[str, str]]] = {}\n    for family in FAMILIES:\n        family_rows = events.loc[events["event_family"] == family]\n        keys[family] = set(\n            zip(family_rows["symbol"], family_rows["announced_date"], strict=False)\n        )\n    rows: list[dict[str, Any]] = []\n    for left in FAMILIES:\n        for right in FAMILIES:\n            intersection = keys[left] & keys[right]\n            denominator = len(keys[left] | keys[right])\n            rows.append(\n                {\n                    "left_family": left,\n                    "right_family": right,\n                    "overlap_count": len(intersection),\n                    "jaccard": len(intersection) / denominator if denominator else 0.0,\n                }\n            )\n    return pd.DataFrame(rows)\n\n\n'''
    text = replace_once(text, anchor, function, "phase2 overlap function")
    text = replace_once(
        text,
        '    write_csv(output / "overlap_matrix.csv", overlap_matrix(event_frame))\n',
        '    write_csv(output / "overlap_matrix.csv", phase2_overlap_matrix(event_frame))\n',
        "phase2 overlap call",
    )
    BUILDER.write_text(text, encoding="utf-8")
    py_compile.compile(str(BUILDER), doraise=True)


def patch_tests() -> None:
    text = TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "import pandas as pd\n\nfrom src.data.company_events",
        "import pandas as pd\n\nfrom scripts.data.build_cn130_pit_event_families_phase2 import phase2_overlap_matrix\nfrom src.data.company_events",
        "phase2 overlap test import",
    )
    addition = '''\n\ndef test_cninfo_markup_is_removed_before_title_classification() -> None:\n    assert (\n        classify_buyback_title("关于<em>回购</em>公司股份的进展公告")\n        == "progress"\n    )\n    assert (\n        classify_restricted_unlock_title(\n            "关于首次公开发行部分<em>限</em><em>售</em>股上市流通公告"\n        )\n        == "scheduled"\n    )\n\n\ndef test_unlock_listing_language_can_include_incentive_plan_but_not_broker_opinion() -> None:\n    assert (\n        classify_restricted_unlock_title(\n            "关于2021年限制性股票激励计划解除限售股份上市流通的提示性公告"\n        )\n        == "scheduled"\n    )\n    assert (\n        classify_restricted_unlock_title(\n            "证券公司关于首次公开发行限售股上市流通的核查意见"\n        )\n        is None\n    )\n\n\ndef test_phase2_overlap_matrix_uses_phase2_families() -> None:\n    events = pd.DataFrame(\n        [\n            {"event_family": "buyback", "symbol": "000001", "announced_date": "2024-01-01"},\n            {\n                "event_family": "restricted_unlock",\n                "symbol": "000001",\n                "announced_date": "2024-01-01",\n            },\n        ]\n    )\n\n    result = phase2_overlap_matrix(events)\n\n    assert set(result["left_family"]) == {"buyback", "restricted_unlock"}\n    cross = result.loc[\n        (result["left_family"] == "buyback")\n        & (result["right_family"] == "restricted_unlock")\n    ].iloc[0]\n    assert cross["overlap_count"] == 1\n    assert cross["jaccard"] == 1.0\n'''
    if "test_cninfo_markup_is_removed_before_title_classification" in text:
        raise RuntimeError("markup regression tests already exist")
    TEST.write_text(text + addition, encoding="utf-8")
    py_compile.compile(str(TEST), doraise=True)


def main() -> int:
    patch_adapter()
    patch_builder()
    patch_tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
