from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any

import requests

API_BASE_URL = "https://api.discogs.com"
USER_AGENT = "VinylPi64/1.0 +https://github.com/simontrost/VinylPi64"


class DiscogsError(RuntimeError):
    pass


class DiscogsClient:
    def __init__(self, token: str, *, timeout: float = 20.0) -> None:
        token = (token or "").strip()
        if not token:
            raise DiscogsError("No Discogs personal access token configured.")

        self.timeout = float(timeout)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Discogs token={token}",
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.discogs.v2.discogs+json",
            }
        )
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0

    def _wait_for_rate_limit(self) -> None:
        # Authenticated Discogs clients are limited to 60 requests/minute.
        minimum_interval = 1.05
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < minimum_interval:
            time.sleep(minimum_interval - elapsed)

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{API_BASE_URL}{path}"
        with self._request_lock:
            self._wait_for_rate_limit()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                raise DiscogsError(f"Discogs request failed: {exc}") from exc
            finally:
                self._last_request_at = time.monotonic()

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            try:
                wait_seconds = max(2.0, float(retry_after or 60))
            except (TypeError, ValueError):
                wait_seconds = 60.0
            time.sleep(wait_seconds)
            return self._get(path, params=params)

        if response.status_code in {401, 403}:
            raise DiscogsError("Discogs rejected the token. Create a new personal access token and reconnect.")
        if response.status_code == 404:
            raise DiscogsError("The requested Discogs resource was not found.")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            message = ""
            try:
                message = (response.json() or {}).get("message") or ""
            except ValueError:
                message = response.text[:200]
            raise DiscogsError(
                f"Discogs API returned HTTP {response.status_code}"
                + (f": {message}" if message else ".")
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise DiscogsError("Discogs returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise DiscogsError("Discogs returned an unexpected response.")
        return payload

    def identity(self) -> dict[str, Any]:
        return self._get("/oauth/identity")

    def iter_collection_releases(
        self,
        username: str,
        *,
        folder_id: int = 0,
        per_page: int = 100,
    ) -> Iterator[dict[str, Any]]:
        page = 1
        while True:
            payload = self._get(
                f"/users/{username}/collection/folders/{int(folder_id)}/releases",
                params={"page": page, "per_page": int(per_page)},
            )
            releases = payload.get("releases") or []
            for release in releases:
                if isinstance(release, dict):
                    yield release

            pagination = payload.get("pagination") or {}
            pages = int(pagination.get("pages") or page)
            if page >= pages:
                break
            page += 1

    def get_release(self, release_id: int) -> dict[str, Any]:
        return self._get(f"/releases/{int(release_id)}")
