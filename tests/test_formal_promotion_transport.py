from __future__ import annotations

import urllib.request

from scripts.run_formal_promotion import CrossOriginCredentialStrippingRedirect


def test_cross_origin_redirect_strips_api_credentials() -> None:
    request = urllib.request.Request(
        "https://api.github.com/repos/o/r/actions/artifacts/1/zip",
        headers={
            "Authorization": "Bearer secret",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    redirected = CrossOriginCredentialStrippingRedirect().redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://signed.example/artifact.zip",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("X-GitHub-Api-Version") is None
