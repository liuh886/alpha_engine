from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request

import pytest

import src.artifacts.strategy_operations_runtime as runtime


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_oidc_token_request_uses_github_runner_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Request] = []

    def fake_urlopen(request: Request, timeout: int) -> _Response:
        assert timeout == 20
        seen.append(request)
        return _Response({"value": "oidc-token"})

    monkeypatch.setattr(runtime, "urlopen", fake_urlopen)
    token = runtime.request_github_oidc_token(
        environ={
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://actions.example/token?api=1",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "runner-token",
        }
    )

    assert token == "oidc-token"
    assert seen[0].full_url.endswith("api=1&audience=alpha-engine-supabase")
    assert seen[0].get_header("Authorization") == "Bearer runner-token"


def test_missing_oidc_environment_fails_closed() -> None:
    with pytest.raises(runtime.StrategyOperationsRuntimeError, match="ACTIONS_ID_TOKEN_REQUEST_URL"):
        runtime.request_github_oidc_token(environ={})


def test_publish_uses_oidc_bearer_and_exact_operations_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations = {
        "schema_version": "2.1.0",
        "research_only": True,
        "trade_ready": False,
        "records": [{"strategy_id": "fixture", "model_version_id": "fixture_v1"}],
    }
    source = tmp_path / "snapshots.json"
    source.write_text(json.dumps(operations), encoding="utf-8")
    seen: list[Request] = []

    def fake_urlopen(request: Request, timeout: int) -> _Response:
        seen.append(request)
        if len(seen) == 1:
            assert timeout == 20
            return _Response({"value": "oidc-token"})
        assert timeout == 30
        return _Response(
            {
                "status": "published",
                "strategy_count": 1,
                "strategy_ids": ["fixture"],
                "research_only": True,
                "trade_ready": False,
            }
        )

    monkeypatch.setattr(runtime, "urlopen", fake_urlopen)
    result = runtime.publish_strategy_operations(
        source,
        publish_url="https://runtime.example/publish",
        environ={
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://actions.example/token?api=1",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "runner-token",
        },
    )

    assert result["status"] == "published"
    publish_request = seen[1]
    assert publish_request.full_url == "https://runtime.example/publish"
    assert publish_request.get_header("Authorization") == "Bearer oidc-token"
    assert json.loads(bytes(publish_request.data or b"").decode("utf-8")) == operations
