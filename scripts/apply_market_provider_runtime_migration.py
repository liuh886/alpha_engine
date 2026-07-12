"""One-time mechanical migration for issue #127. Deleted before merge."""

from pathlib import Path


def _replace(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"migration anchor not found: {label}")
    return text.replace(old, new, 1)


def patch(path: Path, market: str) -> None:
    text = path.read_text(encoding="utf-8")
    import_anchor = "from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init\n"
    import_line = (
        "from src.data.market_provider import "
        "load_provider_manifest, market_provider_path\n"
    )
    text = _replace(text, import_anchor, import_anchor + import_line, f"{market} import")
    text = _replace(
        text,
        '    provider_uri: str | Path | None = None\n    _resolved_provider_uri: str = ""\n',
        '    provider_uri: str | Path | None = None\n'
        '    _resolved_provider_uri: str = ""\n'
        '    _provider_identity_sha256: str = ""\n',
        f"{market} fields",
    )

    if market == "cn":
        old_initialize = (
            "    def initialize(self, repository_root: Path) -> None:\n"
            '        provider = Path(self.provider_uri) if self.provider_uri else repository_root / "data" / "watchlist"\n'
            "        self._resolved_provider_uri = str(provider.resolve())\n"
            "        safe_qlib_init(\n"
        )
    else:
        old_initialize = (
            "    def initialize(self, repository_root: Path) -> None:\n"
            "        provider = (\n"
            "            Path(self.provider_uri)\n"
            "            if self.provider_uri is not None\n"
            '            else repository_root / "data" / "watchlist"\n'
            "        )\n"
            "        self._resolved_provider_uri = str(provider.resolve())\n"
            "        safe_qlib_init(\n"
        )

    new_initialize = (
        "    def initialize(self, repository_root: Path) -> None:\n"
        "        provider = (\n"
        "            Path(self.provider_uri)\n"
        "            if self.provider_uri is not None\n"
        f'            else market_provider_path(repository_root, "{market}")\n'
        "        )\n"
        "        manifest = load_provider_manifest(\n"
        "            provider,\n"
        f'            expected_market="{market}",\n'
        "            required=self.provider_uri is None,\n"
        "            verify_files=True,\n"
        "        )\n"
        "        self._provider_identity_sha256 = (\n"
        '            "" if manifest is None else str(manifest["provider_identity_sha256"])\n'
        "        )\n"
        "        self._resolved_provider_uri = str(provider.resolve())\n"
        "        safe_qlib_init(\n"
    )
    text = _replace(text, old_initialize, new_initialize, f"{market} initialize")
    text = _replace(
        text,
        '            "provider_uri": self._resolved_provider_uri,\n'
        f'            "market": "{market}",\n',
        '            "provider_uri": self._resolved_provider_uri,\n'
        '            "provider_identity_sha256": self._provider_identity_sha256,\n'
        f'            "market": "{market}",\n',
        f"{market} metadata",
    )
    path.write_text(text, encoding="utf-8")


patch(Path("src/research/cn_qlib_execution_adapter.py"), "cn")
patch(Path("src/research/us_qlib_execution_adapter.py"), "us")
