import re

_SAFE_TAG_RE = re.compile(r"[^A-Za-z0-9_-]+")

def sanitize_tag(value: str, *, max_len: int = 40) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    value = _SAFE_TAG_RE.sub("_", value)
    value = value.strip("_")
    if not value:
        return ""
    if len(value) > max_len:
        value = value[:max_len].rstrip("_")
    return value
