from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv, set_key

from vinylpi.paths import BASE_DIR

SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_ACCOUNTS_BASE = "https://accounts.spotify.com"
SPOTIFY_SCOPES = (
    "user-read-currently-playing",
    "user-read-playback-state",
)


class SpotifyError(RuntimeError):
    pass


class SpotifyNotConfigured(SpotifyError):
    pass


class SpotifyNotAuthorized(SpotifyError):
    pass


@dataclass(slots=True)
class SpotifyTrack:
    track_id: str
    title: str
    artist: str
    artist_id: str | None
    album: str | None
    cover_url: str | None
    duration_ms: int | None
    progress_ms: int | None
    is_playing: bool
    spotify_url: str | None
    device_name: str | None = None
    genre: str | None = None


def _env_path() -> Path:
    return BASE_DIR / ".env"


def load_spotify_env() -> None:
    # Keep backwards compatibility with the existing Discogs/environment file,
    # but let the dedicated .env override it for Spotify settings.
    load_dotenv(BASE_DIR / "vinylpi.env", override=False)
    load_dotenv(_env_path(), override=True)


def spotify_env_status() -> dict:
    load_spotify_env()
    client_id = (os.getenv("SPOTIFY_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("SPOTIFY_CLIENT_SECRET") or "").strip()
    refresh_token = (os.getenv("SPOTIFY_REFRESH_TOKEN") or "").strip()
    access_token = (os.getenv("SPOTIFY_ACCESS_TOKEN") or "").strip()
    redirect_uri = (os.getenv("SPOTIFY_REDIRECT_URI") or "").strip()
    return {
        "configured": bool(client_id and client_secret),
        "connected": bool(refresh_token or access_token),
        "has_refresh_token": bool(refresh_token),
        "redirect_uri": redirect_uri,
    }


def clear_refresh_token() -> None:
    path = _env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    set_key(str(path), "SPOTIFY_REFRESH_TOKEN", "", quote_mode="never")
    os.environ.pop("SPOTIFY_REFRESH_TOKEN", None)


def save_refresh_token(refresh_token: str) -> None:
    token = (refresh_token or "").strip()
    if not token:
        raise SpotifyError("Spotify did not return a refresh token")

    path = _env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    set_key(str(path), "SPOTIFY_REFRESH_TOKEN", token, quote_mode="never")
    os.environ["SPOTIFY_REFRESH_TOKEN"] = token


class SpotifyClient:
    def __init__(self, *, timeout: float = 10.0):
        load_spotify_env()
        self.timeout = float(timeout)
        self.client_id = (os.getenv("SPOTIFY_CLIENT_ID") or "").strip()
        self.client_secret = (os.getenv("SPOTIFY_CLIENT_SECRET") or "").strip()
        self.refresh_token = (os.getenv("SPOTIFY_REFRESH_TOKEN") or "").strip()
        self.redirect_uri = (os.getenv("SPOTIFY_REDIRECT_URI") or "").strip()
        self._access_token = (os.getenv("SPOTIFY_ACCESS_TOKEN") or "").strip() or None
        self._access_token_expires_at = 0.0
        self._artist_genre_cache: dict[str, str | None] = {}

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def authorized(self) -> bool:
        return bool(self.refresh_token or self._access_token)

    def _require_configured(self) -> None:
        if not self.configured:
            raise SpotifyNotConfigured(
                "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are missing in .env"
            )

    def build_authorize_url(self, *, state: str, redirect_uri: str | None = None) -> str:
        self._require_configured()
        callback = (redirect_uri or self.redirect_uri or "").strip()
        if not callback:
            raise SpotifyNotConfigured("SPOTIFY_REDIRECT_URI is missing in .env")
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": callback,
            "scope": " ".join(SPOTIFY_SCOPES),
            "state": state,
            "show_dialog": "false",
        }
        return f"{SPOTIFY_ACCOUNTS_BASE}/authorize?{urlencode(params)}"

    def exchange_code(self, code: str, *, redirect_uri: str | None = None) -> dict:
        self._require_configured()
        callback = (redirect_uri or self.redirect_uri or "").strip()
        if not callback:
            raise SpotifyNotConfigured("SPOTIFY_REDIRECT_URI is missing in .env")

        try:
            response = requests.post(
                f"{SPOTIFY_ACCOUNTS_BASE}/api/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": callback,
                },
                auth=(self.client_id, self.client_secret),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SpotifyError(f"Spotify authorization request failed: {exc}") from exc
        if response.status_code >= 400:
            raise SpotifyError(f"Spotify authorization failed ({response.status_code})")
        data = response.json()
        self._accept_token_response(data)
        if data.get("refresh_token"):
            save_refresh_token(str(data["refresh_token"]))
            self.refresh_token = str(data["refresh_token"])
        return data

    def _accept_token_response(self, data: dict) -> None:
        access_token = str(data.get("access_token") or "").strip()
        if not access_token:
            raise SpotifyError("Spotify token response did not contain an access token")
        self._access_token = access_token
        expires_in = int(data.get("expires_in") or 3600)
        self._access_token_expires_at = time.monotonic() + max(30, expires_in - 60)

        rotated_refresh = str(data.get("refresh_token") or "").strip()
        if rotated_refresh:
            self.refresh_token = rotated_refresh
            save_refresh_token(rotated_refresh)

    def refresh_access_token(self) -> str:
        self._require_configured()
        if not self.refresh_token:
            raise SpotifyNotAuthorized(
                "SPOTIFY_REFRESH_TOKEN is missing. Connect Spotify from the dashboard first."
            )

        try:
            response = requests.post(
                f"{SPOTIFY_ACCOUNTS_BASE}/api/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                },
                auth=(self.client_id, self.client_secret),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SpotifyError(f"Spotify token refresh request failed: {exc}") from exc
        if response.status_code >= 400:
            try:
                error_code = str((response.json() or {}).get("error") or "")
            except Exception:
                error_code = ""
            if error_code == "invalid_grant":
                clear_refresh_token()
                self.refresh_token = ""
                raise SpotifyNotAuthorized(
                    "Spotify authorization expired or was revoked. Reconnect Spotify."
                )
            raise SpotifyNotAuthorized(
                f"Spotify token refresh failed ({response.status_code}). Reconnect Spotify."
            )
        self._accept_token_response(response.json())
        return str(self._access_token)

    def _get_access_token(self) -> str:
        if self._access_token and (
            self._access_token_expires_at == 0.0
            or time.monotonic() < self._access_token_expires_at
        ):
            return self._access_token
        return self.refresh_access_token()

    def _api_get(self, path: str, *, retry_auth: bool = True) -> requests.Response:
        token = self._get_access_token()
        try:
            response = requests.get(
                f"{SPOTIFY_API_BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SpotifyError(f"Spotify API request failed: {exc}") from exc
        if response.status_code == 401 and retry_auth and self.refresh_token:
            self._access_token = None
            self._access_token_expires_at = 0.0
            self.refresh_access_token()
            return self._api_get(path, retry_auth=False)
        return response

    def get_artist_genre(self, artist_id: str | None) -> str | None:
        if not artist_id:
            return None
        if artist_id in self._artist_genre_cache:
            return self._artist_genre_cache[artist_id]
        try:
            response = self._api_get(f"/artists/{artist_id}")
            if response.status_code != 200:
                self._artist_genre_cache[artist_id] = None
                return None
            genres = response.json().get("genres") or []
            genre = str(genres[0]).strip() if genres else None
        except Exception:
            genre = None
        self._artist_genre_cache[artist_id] = genre
        return genre

    @staticmethod
    def parse_currently_playing(data: dict) -> SpotifyTrack | None:
        item = data.get("item") or {}
        if not item or str(item.get("type") or "track") != "track":
            return None

        artists = item.get("artists") or []
        primary_artist = artists[0] if artists else {}
        artist = str(primary_artist.get("name") or "UNKNOWN").strip()
        artist_id = str(primary_artist.get("id") or "").strip() or None
        title = str(item.get("name") or "UNKNOWN").strip()
        track_id = str(item.get("id") or "").strip()
        if not track_id:
            track_id = f"local:{artist.casefold()}:{title.casefold()}"

        album = item.get("album") or {}
        images = album.get("images") or []
        cover_url = None
        if images:
            # Spotify returns largest first. The Pixoo renderer downsamples anyway.
            cover_url = str((images[0] or {}).get("url") or "").strip() or None

        external_urls = item.get("external_urls") or {}
        device = data.get("device") or {}
        return SpotifyTrack(
            track_id=track_id,
            title=title,
            artist=artist,
            artist_id=artist_id,
            album=str(album.get("name") or "").strip() or None,
            cover_url=cover_url,
            duration_ms=int(item.get("duration_ms")) if item.get("duration_ms") is not None else None,
            progress_ms=int(data.get("progress_ms")) if data.get("progress_ms") is not None else None,
            is_playing=bool(data.get("is_playing")),
            spotify_url=str(external_urls.get("spotify") or "").strip() or None,
            device_name=str(device.get("name") or "").strip() or None,
        )

    def get_currently_playing(self) -> SpotifyTrack | None:
        if not self.authorized:
            raise SpotifyNotAuthorized(
                "Spotify is not connected. Use Connect Spotify in the dashboard."
            )
        response = self._api_get("/me/player/currently-playing")
        if response.status_code == 204:
            return None
        if response.status_code == 403:
            raise SpotifyError("Spotify denied playback access. Check the app scopes/account.")
        if response.status_code >= 400:
            raise SpotifyError(f"Spotify currently-playing request failed ({response.status_code})")
        track = self.parse_currently_playing(response.json())
        if track and track.artist_id:
            track.genre = self.get_artist_genre(track.artist_id)
        return track
