from __future__ import annotations

from pathlib import Path

path = Path("scripts/run_cn130_pit_disclosure_reaction.py")
text = path.read_text(encoding="utf-8")
old = '''    left = frame.iloc[:, 0].to_numpy(float)
    right = frame.iloc[:, 1].to_numpy(float)
'''
new = '''    left = frame.iloc[:, 0].to_numpy(dtype=float, copy=True)
    right = frame.iloc[:, 1].to_numpy(dtype=float, copy=True)
'''
if text.count(old) != 1:
    raise RuntimeError("expected residual-array block not found exactly once")
path.write_text(text.replace(old, new), encoding="utf-8")
