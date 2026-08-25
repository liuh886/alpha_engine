from __future__ import annotations

import json
import urllib.request

import pytest

from src.data.sec_transport import SecTransport, SecTransportError


def test_direct_transport_ignores_ambient_proxy_settings(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "https://ambient.invalid:8443")
    monkeypatch.delenv("SEC_EGRESS_MODE", raising=False)
    monkeypatch.delenv("SEC_EGRESS_PROXY_URL", raising=False)
    monkeypatch.delenv("SEC_EGRESS_PROXY_ID", raising=False)
    transport = SecTransport.from_env()
    assert transport.evidence() == {
        "egress_mode": "direct",
        "proxy_configured": False,
        "proxy_id": None,
        "target_hosts": ["data.sec.gov", "sec.gov", "www.sec.gov"],
    }


def test_declared_proxy_never_exposes_url_or_credentials(monkeypatch) -> None:
    secret_url = "https://user:secret@egress.example:8443"
    monkeypatch.setenv("SEC_EGRESS_MODE", "declared_proxy")
    monkeypatch.setenv("SEC_EGRESS_PROXY_URL", secret_url)
    monkeypatch.setenv("SEC_EGRESS_PROXY_ID", "us-sec-egress-1")
    evidence = SecTransport.from_env().evidence()
    encoded = json.dumps(evidence)
    assert evidence["proxy_id"] == "us-sec-egress-1"
    assert "egress.example" not in encoded
    assert "secret" not in encoded


@pytest.mark.parametrize(
    "url",
    [
        "http://egress.example:8080",
        "https://egress.example/path",
        "https://egress.example?token=secret",
    ],
)
def test_declared_proxy_rejects_unsafe_urls(monkeypatch, url: str) -> None:
    monkeypatch.setenv("SEC_EGRESS_MODE", "declared_proxy")
    monkeypatch.setenv("SEC_EGRESS_PROXY_URL", url)
    monkeypatch.setenv("SEC_EGRESS_PROXY_ID", "us-sec-egress-1")
    with pytest.raises(SecTransportError, match="HTTPS origin"):
        SecTransport.from_env()


def test_transport_rejects_non_sec_target_before_network(monkeypatch) -> None:
    monkeypatch.delenv("SEC_EGRESS_MODE", raising=False)
    monkeypatch.delenv("SEC_EGRESS_PROXY_URL", raising=False)
    monkeypatch.delenv("SEC_EGRESS_PROXY_ID", raising=False)
    transport = SecTransport.from_env()
    with pytest.raises(SecTransportError, match="approved HTTPS hosts"):
        transport.open(
            urllib.request.Request("https://example.com/companyfacts.json"),
            timeout=1,
        )


def test_transport_rejects_nonstandard_sec_port(monkeypatch) -> None:
    monkeypatch.delenv("SEC_EGRESS_MODE", raising=False)
    monkeypatch.delenv("SEC_EGRESS_PROXY_URL", raising=False)
    monkeypatch.delenv("SEC_EGRESS_PROXY_ID", raising=False)
    transport = SecTransport.from_env()
    with pytest.raises(SecTransportError, match="standard HTTPS port"):
        transport.open(
            urllib.request.Request("https://data.sec.gov:8443/companyfacts.json"),
            timeout=1,
        )
