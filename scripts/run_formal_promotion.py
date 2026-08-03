from __future__ import annotations

import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.formal_promotion import main as promotion_main


class CrossOriginCredentialStrippingRedirect(urllib.request.HTTPRedirectHandler):
    """Keep GitHub auth on API calls but remove it from signed storage redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if (
            redirected is not None
            and urlsplit(req.full_url).netloc != urlsplit(newurl).netloc
        ):
            redirected.remove_header("Authorization")
            redirected.remove_header("X-GitHub-Api-Version")
        return redirected


def install_safe_artifact_transport() -> None:
    urllib.request.install_opener(
        urllib.request.build_opener(CrossOriginCredentialStrippingRedirect())
    )


def main() -> None:
    install_safe_artifact_transport()
    promotion_main()


if __name__ == "__main__":
    main()
