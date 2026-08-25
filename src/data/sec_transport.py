"""Fail-closed SEC HTTP transport with optional declared egress."""

from __future__ import annotations

import gzip
import json
import os
import re
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


ALLOWED_SEC_HOSTS = frozenset({"data.sec.gov", "www.sec.gov", "sec.gov"})
_PROXY_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class SecTransportError(ValueError):
    """Raised when SEC transport governance is invalid."""


def read_sec_json_response(response: Any) -> dict[str, Any]:
    raw = response.read()
    encoding = str(response.headers.get("Content-Encoding", "") or "").strip().lower()
    if raw.startswith(b"\x1f\x8b") or encoding == "gzip":
        raw = gzip.decompress(raw)
    elif encoding == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise SecTransportError("SEC response must be a JSON object")
    return payload


def _validate_sec_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SEC_HOSTS:
        raise SecTransportError("SEC transport target is outside the approved HTTPS hosts")
    if parsed.username or parsed.password:
        raise SecTransportError("SEC target URL must not contain credentials")
    if parsed.port not in {None, 443}:
        raise SecTransportError("SEC target URL must use the standard HTTPS port")


class SecRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects away from the approved SEC hosts."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str):
        _validate_sec_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass
class SecTransport:
    mode: str
    proxy_id: str | None
    _opener: Any

    @classmethod
    def from_env(cls) -> "SecTransport":
        mode = str(os.getenv("SEC_EGRESS_MODE", "direct")).strip().lower()
        proxy_url = str(os.getenv("SEC_EGRESS_PROXY_URL", "")).strip()
        proxy_id = str(os.getenv("SEC_EGRESS_PROXY_ID", "")).strip().lower()
        if mode not in {"direct", "declared_proxy"}:
            raise SecTransportError("SEC_EGRESS_MODE must be direct or declared_proxy")
        if mode == "direct":
            if proxy_url or proxy_id:
                raise SecTransportError("direct SEC egress cannot declare proxy settings")
            proxy_handler = urllib.request.ProxyHandler({})
            resolved_proxy_id = None
        else:
            parsed = urlsplit(proxy_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise SecTransportError("declared SEC proxy must be an HTTPS origin URL")
            if not _PROXY_ID.fullmatch(proxy_id):
                raise SecTransportError("SEC_EGRESS_PROXY_ID must be a non-secret slug")
            proxy_handler = urllib.request.ProxyHandler({"https": proxy_url})
            resolved_proxy_id = proxy_id
        opener = urllib.request.build_opener(proxy_handler, SecRedirectHandler())
        return cls(mode=mode, proxy_id=resolved_proxy_id, _opener=opener)

    def open(self, request: urllib.request.Request, *, timeout: float):
        _validate_sec_url(request.full_url)
        return self._opener.open(request, timeout=timeout)

    def evidence(self) -> dict[str, Any]:
        return {
            "egress_mode": self.mode,
            "proxy_configured": self.mode == "declared_proxy",
            "proxy_id": self.proxy_id,
            "target_hosts": sorted(ALLOWED_SEC_HOSTS),
        }
