from __future__ import annotations

from pathlib import Path

path = Path("scripts/run_cn130_pit_fundamental_veto.py")
text = path.read_text(encoding="utf-8")
replacements = [
    (
        'CALIBRATION_WINDOWS = ("2022H1", "2022H2", "2023H1", "2023H2")',
        'CALIBRATION_WINDOWS = ("2022H2", "2023H1", "2023H2")',
    ),
    (
        '"> 2022–2023只校准组件与架构；2024–2025只允许一次冻结验证。",',
        '"> 2022H2–2023H2只校准组件与架构；2024–2025只允许一次冻结验证。",',
    ),
    (
        'f"{row.positive_half_years}/4 | {row.worst_half_year_rank_ic:.4f} | {row.mean_spread:.2%} | "',
        'f"{row.positive_half_years}/{len(CALIBRATION_WINDOWS)} | {row.worst_half_year_rank_ic:.4f} | {row.mean_spread:.2%} | "',
    ),
    (
        'f"{row.worst_window_relative_excess:.2%} | {row.positive_windows}/4 | "',
        'f"{row.worst_window_relative_excess:.2%} | {row.positive_windows}/{len(CALIBRATION_WINDOWS)} | "',
    ),
]
for old, new in replacements:
    if old not in text:
        raise RuntimeError(f"expected calibration text not found: {old}")
    text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
