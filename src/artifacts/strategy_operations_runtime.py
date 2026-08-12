from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_PUBLISH_URL = (
    "https://blgwlycfcwvsupmqyqwn.supabase.co/functions/v1/"
    "alpha-engine-publish-strategy-operations"
)
DEFAULT_OIDC_AUDIENCE = "alpha-engine-supabase"


class StrategyOperationsRuntimeError(RuntimeError):
    pass


def _require_env(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise StrategyOperationsRuntimeError(f"missing GitHub Actions OIDC environment: {name}")
    return value


def request_github_oidc_token(
    *,
    audience: str = DEFAULT_OIDC_AUDIENCE,
    environ: Mapping[str, str] | None = None,
) -> str:
    env = os.environ if environ is None else environ
    request_url = _require_env(env, "ACTIONS_ID_TOKEN_REQUEST_URL")
    request_token = _require_env(env, "ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    separator = "&" if "?" in request_url else "?"
    url = f"{request_url}{separator}{urlencode({'audience': audience})}"
    request = Request(
        url,
        headers={"Authorization": f"Bearer {request_token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 - GitHub-provided HTTPS endpoint.
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        raise StrategyOperationsRuntimeError(f"GitHub OIDC token request failed: {exc}") from exc
    token = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise StrategyOperationsRuntimeError("GitHub OIDC token response did not include value")
    return token


def publish_strategy_operations(
    input_path: Path,
    *,
    publish_url: str = DEFAULT_PUBLISH_URL,
    audience: str = DEFAULT_OIDC_AUDIENCE,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    try:
        operations = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StrategyOperationsRuntimeError(f"cannot read Strategy Operations payload: {exc}") from exc
    if not isinstance(operations, dict):
        raise StrategyOperationsRuntimeError("Strategy Operations payload root must be an object")

    token = request_github_oidc_token(audience=audience, environ=environ)
    request = Request(
        publish_url,
        data=json.dumps(operations, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - governed Supabase HTTPS endpoint.
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise StrategyOperationsRuntimeError(
            f"runtime publication rejected with HTTP {exc.code}: {body}"
        ) from exc
    except (URLError, OSError, json.JSONDecodeError) as exc:
        raise StrategyOperationsRuntimeError(f"runtime publication failed: {exc}") from exc
    if not isinstance(result, dict) or result.get("status") != "published":
        raise StrategyOperationsRuntimeError("runtime publisher returned an invalid success response")
    return result
