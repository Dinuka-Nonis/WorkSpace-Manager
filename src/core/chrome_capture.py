"""Chrome tab capture via DevTools Protocol."""

import logging
from typing import Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from src.db.models import ChromeTab

logger = logging.getLogger("workspace.chrome")

SKIP_URL_PREFIXES = ("chrome://", "chrome-extension://", "devtools://", "about:", "data:")


class ChromeCapture:
    def __init__(self, session_id: int, port: int = 9222):
        self.session_id = session_id
        self.port = port
        self._base_url = f"http://localhost:{port}"

    def is_available(self) -> bool:
        if not REQUESTS_AVAILABLE:
            return False
        try:
            r = requests.get(f"{self._base_url}/json/version", timeout=1.5)
            return r.status_code == 200
        except:
            return False

    def capture(self, snapshot_id: int) -> list[ChromeTab]:
        if not self.is_available():
            return []

        try:
            r = requests.get(f"{self._base_url}/json/list", timeout=1.5)
            data = r.json()
        except Exception as e:
            logger.warning(f"Chrome CDP failed: {e}")
            return []

        tabs = []
        for item in data:
            if item.get("type") != "page":
                continue

            url = item.get("url", "")
            if any(url.startswith(p) for p in SKIP_URL_PREFIXES) or not url:
                continue

            tabs.append(ChromeTab(
                id=None,
                session_id=self.session_id,
                snapshot_id=snapshot_id,
                window_id=0,
                tab_id=item.get("id", ""),
                url=url,
                title=item.get("title", ""),
            ))

        logger.debug(f"Chrome: captured {len(tabs)} tabs")
        return tabs