from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

from vinylpi.core.database import get_connection, init_db
from vinylpi.core.genre_tags import normalize_genre
from vinylpi.paths import BASE_DIR, get_active_db_path

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


def load_spotify_env() -> None:
    """Load app-wide Spotify credentials without exposing them to the browser."""
    load_dotenv(BASE_DIR / "vinylpi.env", override=False)
    load_dotenv(BASE_DIR / ".env", override=True)


def _profile_db_path(db_path: Path | str | None = None) -> Path:
    return Path(db_path) if db_path is not None else get_active_db_path()


def get_spotify_account(db_path: Path | str | None = None) -> dict | None:
    path = _profile_db_path(db_path)
    init_db(path)
    with get_connection(path) as conn:
        row = conn.execute(
            """
            SELECT account_id, spotify_user_id, display_name, external_url,
                   connected_at, updated_at
            FROM spotify_account WHERE id = 1
            """
        ).fetchone()
    if not row:
        return None
    return {key: row[key] for key in row.keys()}


def _get_refresh_token(db_path: Path | str | None = None) -> str:
    path = _profile_db_path(db_path)
    init_db(path)
    with get_connection(path) as conn:
        row = conn.execute(
            "SELECT refresh_token FROM spotify_account WHERE id = 1"
        ).fetchone()
    return str(row["refresh_token"] or "").strip() if row else ""


def save_spotify_account(
    refresh_token: str,
    *,
    account_id: str | None = None,
    spotify_user_id: str | None = None,
    display_name: str | None = None,
    external_url: str | None = None,
    db_path: Path | str | None = None,
) -> None:
    token = str(refresh_token or "").strip()
    if not token:
        raise SpotifyError("Spotify did not return a refresh token")

    path = _profile_db_path(db_path)
    init_db(path)
    now = int(time.time())
    with get_connection(path) as conn:
        conn.execute(
            """
            INSERT INTO spotify_account (
                id, refresh_token, account_id, spotify_user_id, display_name,
                external_url, connected_at, updated_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                refresh_token = excluded.refresh_token,
                account_id = COALESCE(excluded.account_id, spotify_account.account_id),
                spotify_user_id = COALESCE(excluded.spotify_user_id, spotify_account.spotify_user_id),
                display_name = COALESCE(excluded.display_name, spotify_account.display_name),
                external_url = COALESCE(excluded.external_url, spotify_account.external_url),
                updated_at = excluded.updated_at
            """,
            (
                token,
                account_id,
                spotify_user_id,
                display_name,
                external_url,
                now,
                now,
            ),
        )


def update_spotify_account_profile(
    profile: dict,
    *,
    db_path: Path | str | None = None,
) -> None:
    token = _get_refresh_token(db_path)
    if not token:
        return
    external_urls = profile.get("external_urls") or {}
    save_spotify_account(
        token,
        account_id=str(profile.get("account_id") or "").strip() or None,
        spotify_user_id=str(profile.get("id") or "").strip() or None,
        display_name=str(profile.get("display_name") or "").strip() or None,
        external_url=str(external_urls.get("spotify") or "").strip() or None,
        db_path=db_path,
    )


def clear_spotify_account(db_path: Path | str | None = None) -> None:
    path = _profile_db_path(db_path)
    init_db(path)
    with get_connection(path) as conn:
        conn.execute("DELETE FROM spotify_account WHERE id = 1")


def _remove_env_key(path: Path, key: str) -> None:
    """Remove one legacy secret assignment while preserving the rest of the file."""
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=")
        filtered = [line for line in lines if not pattern.match(line)]
        if filtered != lines:
            path.write_text("\n".join(filtered) + "\n", encoding="utf-8")
    except OSError:
        pass


def _migrate_legacy_refresh_token(db_path: Path) -> None:
    """Move the first implementation's global token into the active profile DB."""
    if _get_refresh_token(db_path):
        return
    legacy = str(os.getenv("SPOTIFY_REFRESH_TOKEN") or "").strip()
    if not legacy:
        return
    save_spotify_account(legacy, db_path=db_path)
    _remove_env_key(BASE_DIR / ".env", "SPOTIFY_REFRESH_TOKEN")
    _remove_env_key(BASE_DIR / "vinylpi.env", "SPOTIFY_REFRESH_TOKEN")
    os.environ.pop("SPOTIFY_REFRESH_TOKEN", None)


def spotify_env_status(db_path: Path | str | None = None) -> dict:
    load_spotify_env()
    path = _profile_db_path(db_path)
    _migrate_legacy_refresh_token(path)

    client_id = (os.getenv("SPOTIFY_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("SPOTIFY_CLIENT_SECRET") or "").strip()
    redirect_uri = (os.getenv("SPOTIFY_REDIRECT_URI") or "").strip()
    account = get_spotify_account(path)
    return {
        "configured": bool(client_id and client_secret),
        "connected": bool(_get_refresh_token(path)),
        "has_refresh_token": bool(_get_refresh_token(path)),
        "redirect_uri": redirect_uri,
        "account": account,
    }


_LASTFM_NOISE_TAGS = {
    "seen live",
    "favorites",
    "favourites",
    "favorite",
    "favourite",
    "male vocalists",
    "female vocalists",
    "spotify",
    "my music",
    "awesome",
    "love",
    "under 2000 listeners",
}



_GENRE_HINTS = (
    "rock", "pop", "rap", "hip hop", "hip-hop", "r&b", "soul", "jazz",
    "metal", "punk", "indie", "alternative", "electronic", "electronica",
    "house", "techno", "folk", "country", "classical", "reggae", "ska",
    "funk", "blues", "ambient", "grunge", "emo", "hardcore", "drum",
    "bass", "garage", "trap", "singer", "songwriter", "dance", "disco",
    "gospel", "latin", "afro", "shoegaze", "psychedelic",
)

def _useful_lastfm_tag(value: object) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or len(text) > 48:
        return None
    lower = text.casefold()
    if lower in _LASTFM_NOISE_TAGS or lower.startswith("seen live"):
        return None
    if re.fullmatch(r"(?:19|20)\d0s?", lower):
        return None
    return normalize_genre(text)


class SpotifyClient:
    def __init__(
        self,
        *,
        timeout: float = 10.0,
        profile_db_path: Path | str | None = None,
    ):
        load_spotify_env()
        self.timeout = float(timeout)
        self.profile_db_path = _profile_db_path(profile_db_path)
        _migrate_legacy_refresh_token(self.profile_db_path)

        self.client_id = (os.getenv("SPOTIFY_CLIENT_ID") or "").strip()
        self.client_secret = (os.getenv("SPOTIFY_CLIENT_SECRET") or "").strip()
        self.refresh_token = _get_refresh_token(self.profile_db_path)
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
                "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are missing in vinylpi.env"
            )

    def build_authorize_url(
        self,
        *,
        state: str,
        redirect_uri: str | None = None,
        show_dialog: bool = False,
    ) -> str:
        self._require_configured()
        callback = (redirect_uri or self.redirect_uri or "").strip()
        if not callback:
            raise SpotifyNotConfigured("SPOTIFY_REDIRECT_URI is missing in vinylpi.env")
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": callback,
            "scope": " ".join(SPOTIFY_SCOPES),
            "state": state,
            "show_dialog": "true" if show_dialog else "false",
        }
        return f"{SPOTIFY_ACCOUNTS_BASE}/authorize?{urlencode(params)}"

    def exchange_code(self, code: str, *, redirect_uri: str | None = None) -> dict:
        self._require_configured()
        callback = (redirect_uri or self.redirect_uri or "").strip()
        if not callback:
            raise SpotifyNotConfigured("SPOTIFY_REDIRECT_URI is missing in vinylpi.env")

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
        if not self.refresh_token:
            raise SpotifyError("Spotify authorization did not return a refresh token")

        try:
            profile = self.get_current_user_profile()
            update_spotify_account_profile(profile, db_path=self.profile_db_path)
        except SpotifyError:
            # The token itself is valid; account metadata can be refreshed later.
            pass
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
            existing = get_spotify_account(self.profile_db_path) or {}
            save_spotify_account(
                rotated_refresh,
                account_id=existing.get("account_id"),
                spotify_user_id=existing.get("spotify_user_id"),
                display_name=existing.get("display_name"),
                external_url=existing.get("external_url"),
                db_path=self.profile_db_path,
            )

    def refresh_access_token(self) -> str:
        self._require_configured()
        self.refresh_token = _get_refresh_token(self.profile_db_path)
        if not self.refresh_token:
            raise SpotifyNotAuthorized(
                "This VinylPi profile is not connected to Spotify yet."
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
                clear_spotify_account(self.profile_db_path)
                self.refresh_token = ""
                raise SpotifyNotAuthorized(
                    "Spotify authorization expired or was revoked. Reconnect this profile."
                )
            raise SpotifyNotAuthorized(
                f"Spotify token refresh failed ({response.status_code}). Reconnect this profile."
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

    def get_current_user_profile(self) -> dict:
        response = self._api_get("/me")
        if response.status_code >= 400:
            raise SpotifyError(f"Spotify profile request failed ({response.status_code})")
        data = response.json() or {}
        if not isinstance(data, dict):
            raise SpotifyError("Spotify returned an invalid account profile")
        return data

    def _lastfm_genre(self, artist: str, title: str | None = None) -> str | None:
        api_key = str(os.getenv("LAST_FM_API_KEY") or "").strip()
        artist = str(artist or "").strip()
        title = str(title or "").strip()
        if not api_key or not artist:
            return None

        methods: list[tuple[str, dict[str, str]]] = []
        if title:
            methods.append(("track.getTopTags", {"artist": artist, "track": title}))
        methods.append(("artist.getTopTags", {"artist": artist}))

        for method, params in methods:
            try:
                response = requests.get(
                    "https://ws.audioscrobbler.com/2.0/",
                    params={
                        "method": method,
                        "api_key": api_key,
                        "format": "json",
                        **params,
                    },
                    timeout=self.timeout,
                )
                if response.status_code != 200:
                    continue
                tags = ((response.json() or {}).get("toptags") or {}).get("tag") or []
                candidates = [
                    genre
                    for tag in tags[:12]
                    if (genre := _useful_lastfm_tag((tag or {}).get("name")))
                ]
                for genre in candidates:
                    lower = genre.casefold()
                    if any(hint in lower for hint in _GENRE_HINTS):
                        return genre
                if candidates:
                    return candidates[0]
            except (requests.RequestException, ValueError, TypeError):
                continue
        return None

    def get_artist_genre(
        self,
        artist_id: str | None,
        *,
        artist: str = "",
        title: str = "",
    ) -> str | None:
        cache_key = str(artist_id or artist or "").strip().casefold()
        if cache_key and cache_key in self._artist_genre_cache:
            return self._artist_genre_cache[cache_key]

        genre = None
        if artist_id:
            try:
                response = self._api_get(f"/artists/{artist_id}")
                if response.status_code == 200:
                    genres = response.json().get("genres") or []
                    if genres:
                        genre = normalize_genre(genres[0])
            except Exception:
                genre = None

        # Spotify's artist genres are deprecated and may be empty. The project
        # already supports a LAST_FM_API_KEY, so use Last.fm tags as a fallback.
        if not genre:
            genre = self._lastfm_genre(artist, title)

        if cache_key:
            self._artist_genre_cache[cache_key] = genre
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
                "This VinylPi profile is not connected to Spotify yet."
            )
        response = self._api_get("/me/player/currently-playing")
        if response.status_code == 204:
            return None
        if response.status_code == 403:
            raise SpotifyError("Spotify denied playback access. Check the app scopes/account.")
        if response.status_code >= 400:
            raise SpotifyError(f"Spotify currently-playing request failed ({response.status_code})")
        track = self.parse_currently_playing(response.json())
        if track:
            track.genre = self.get_artist_genre(
                track.artist_id,
                artist=track.artist,
                title=track.title,
            )
        return track
