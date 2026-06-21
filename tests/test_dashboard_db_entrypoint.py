from __future__ import annotations

import scripts.build_dashboard_db as dashboard_builder


def test_main_delegates_to_build_db(monkeypatch):
    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        dashboard_builder,
        "build_db",
        lambda *, model_id="", sync_yaml=False: calls.append((model_id, sync_yaml)),
    )

    dashboard_builder.main(model_id="model-1", sync_yaml=True)

    assert calls == [("model-1", True)]
