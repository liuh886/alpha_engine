#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    port = os.getenv("API_PORT", "8000")
    base_url = f"http://127.0.0.1:{port}"

    try:
        with urlopen(f"{base_url}/api/public/health", timeout=3) as response:
            payload = json.load(response)
            if response.status != 200 or payload.get("status") != "ok":
                return 1

        with urlopen(f"{base_url}/", timeout=3) as response:
            content_type = response.headers.get_content_type()
            if response.status != 200 or content_type != "text/html":
                return 1
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
