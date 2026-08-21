/* Source selector + Spotify dashboard behavior. Loaded after dashboard.js. */

let vinylPiSourceMode = "off";
let vinylPiSourcePollTimer = null;

const vinylPiOriginalRenderDiscogsContext = renderDiscogsContext;
const vinylPiOriginalShowTrackInfo = showTrackInfo;

function setSpotifyFeedback(message = "", type = "") {
    const box = document.getElementById("spotify-feedback");
    if (!box) return;
    box.textContent = message;
    box.classList.toggle("hidden", !message);
    box.classList.remove("is-error", "is-success");
    if (type) box.classList.add(`is-${type}`);
}

function hideDiscogsForSpotify() {
    document.getElementById("discogs-context")?.classList.add("hidden");
    document.getElementById("discogs-add-link")?.classList.add("hidden");
    document.getElementById("discogs-side-flip")?.classList.add("hidden");
}

renderDiscogsContext = function renderDiscogsContextWithSource() {
    if (vinylPiSourceMode === "spotify") {
        hideDiscogsForSpotify();
        return;
    }
    return vinylPiOriginalRenderDiscogsContext();
};

function renderSpotifyTrackInfo() {
    const content = document.getElementById("track-info-content");
    if (!content) return;

    setText("track-info-heading", CURRENT_TRACK.title || "Track Info");

    const songBlock = createInfoBlock("Song");
    appendInfoRow(songBlock, "Title", CURRENT_TRACK.title || "Unknown");
    appendInfoRow(songBlock, "Artist", CURRENT_TRACK.artist || "Unknown");
    appendInfoRow(songBlock, "Album", CURRENT_TRACK.album || "Unknown");
    appendInfoRow(songBlock, "Genre", CURRENT_TRACK.genre);
    appendInfoRow(songBlock, "Duration", formatDuration(CURRENT_TRACK.durationMs));
    appendInfoRow(songBlock, "Spotify track ID", CURRENT_TRACK.trackId);
    if (CURRENT_TRACK.trackId && !String(CURRENT_TRACK.trackId).startsWith("local:")) {
        appendInfoLink(
            songBlock,
            "Open track in Spotify",
            `https://open.spotify.com/track/${encodeURIComponent(CURRENT_TRACK.trackId)}`,
        );
    }

    const artistBlock = createInfoBlock("Artist");
    appendInfoRow(artistBlock, "Name", CURRENT_TRACK.artist || "Unknown");
    appendInfoRow(artistBlock, "Spotify artist ID", CURRENT_TRACK.artistId);
    if (CURRENT_TRACK.artistId) {
        appendInfoLink(
            artistBlock,
            "Open artist in Spotify",
            `https://open.spotify.com/artist/${encodeURIComponent(CURRENT_TRACK.artistId)}`,
        );
    }

    content.replaceChildren(songBlock, artistBlock);
}

showTrackInfo = async function showTrackInfoWithSource() {
    if (vinylPiSourceMode !== "spotify") {
        return vinylPiOriginalShowTrackInfo();
    }
    openTrackInfoDrawer();
    renderSpotifyTrackInfo();
};

function renderSpotifyConnection(spotify = {}) {
    const row = document.getElementById("spotify-connect-row");
    const copy = document.getElementById("spotify-connect-copy");
    const button = document.getElementById("spotify-connect-button");
    if (!row || !copy || !button) return;

    const configured = Boolean(spotify.configured);
    const connected = Boolean(spotify.connected);

    if (!configured) {
        row.classList.remove("hidden");
        copy.textContent = "Spotify credentials are missing in .env.";
        button.classList.add("hidden");
        return;
    }

    if (!connected) {
        row.classList.remove("hidden");
        copy.textContent = "Connect your Spotify account once to enable playback tracking.";
        button.classList.remove("hidden");
        button.textContent = "Connect Spotify";
        return;
    }

    row.classList.add("hidden");
    button.classList.remove("hidden");
}

function updateSourceUI(data = {}) {
    vinylPiSourceMode = ["off", "vinyl", "spotify"].includes(data.mode) ? data.mode : "off";

    document.querySelectorAll("[data-source-mode]").forEach((button) => {
        const active = button.dataset.sourceMode === vinylPiSourceMode;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
    });

    const status = document.getElementById("source-status-text");
    if (status) {
        status.classList.remove("is-off", "is-vinyl", "is-spotify");
        status.classList.add(`is-${vinylPiSourceMode}`);
        status.textContent = {
            off: "Off",
            vinyl: "Vinyl / Shazam",
            spotify: "Spotify",
        }[vinylPiSourceMode];
    }

    renderSpotifyConnection(data.spotify || {});

    const infoLabel = document.querySelector(".track-info-label");
    if (infoLabel) infoLabel.textContent = vinylPiSourceMode === "spotify" ? "Spotify Info" : "Shazam Info";

    if (vinylPiSourceMode === "spotify") {
        hideDiscogsForSpotify();
        if (currentTrackKey) setText("now-playing-label", "Spotify");
    } else if (currentTrackKey) {
        vinylPiOriginalRenderDiscogsContext();
        setText(
            "now-playing-label",
            CURRENT_TRACK.discogsMatchSource === "sequence_inferred" ? "Likely playing" : "Now playing",
        );
    }
}

async function loadSourceStatus() {
    try {
        const response = await fetch("/api/source", { cache: "no-store" });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || `Source request failed: ${response.status}`);
        updateSourceUI(data);
    } catch (error) {
        console.error(error);
        const status = document.getElementById("source-status-text");
        if (status) status.textContent = "Unavailable";
    }
}

async function setSourceMode(mode) {
    document.querySelectorAll("[data-source-mode]").forEach((button) => {
        button.disabled = true;
    });
    setSpotifyFeedback("");

    try {
        const response = await fetch("/api/source", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode }),
        });
        const data = await response.json();
        updateSourceUI(data);

        if (!response.ok || !data.ok) {
            if (data.needs_auth) {
                setSpotifyFeedback("Spotify is configured but not connected yet.", "error");
            } else if (data.needs_config) {
                setSpotifyFeedback("Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env first.", "error");
            } else {
                setSpotifyFeedback(data.error || "Could not change source.", "error");
            }
            return;
        }

        if (mode === "spotify") {
            setSpotifyFeedback("Spotify source enabled.", "success");
        }
    } catch (error) {
        console.error(error);
        setSpotifyFeedback("Could not change the music source.", "error");
    } finally {
        document.querySelectorAll("[data-source-mode]").forEach((button) => {
            button.disabled = false;
        });
        await loadSourceStatus();
    }
}

async function connectSpotify() {
    const button = document.getElementById("spotify-connect-button");
    if (button) button.disabled = true;
    setSpotifyFeedback("Opening Spotify authorization…");

    try {
        const response = await fetch("/api/spotify/auth-url", { cache: "no-store" });
        const data = await response.json();
        if (!response.ok || !data.ok || !data.auth_url) {
            throw new Error(data.error || "Spotify authorization URL unavailable.");
        }
        window.location.assign(data.auth_url);
    } catch (error) {
        console.error(error);
        setSpotifyFeedback(error.message || "Could not start Spotify authorization.", "error");
        if (button) button.disabled = false;
    }
}

function consumeSpotifyCallbackMessage() {
    const url = new URL(window.location.href);
    const result = url.searchParams.get("spotify");
    if (!result) return;

    if (result === "connected") {
        setSpotifyFeedback("Spotify connected successfully.", "success");
    } else {
        const reason = url.searchParams.get("reason") || "authorization_failed";
        setSpotifyFeedback(`Spotify connection failed: ${reason.replaceAll("_", " ")}.`, "error");
    }

    url.searchParams.delete("spotify");
    url.searchParams.delete("reason");
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

function startSourcePolling() {
    if (!vinylPiSourcePollTimer) {
        vinylPiSourcePollTimer = window.setInterval(loadSourceStatus, 4000);
    }
}

function stopSourcePolling() {
    if (vinylPiSourcePollTimer) window.clearInterval(vinylPiSourcePollTimer);
    vinylPiSourcePollTimer = null;
}

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-source-mode]").forEach((button) => {
        button.addEventListener("click", () => setSourceMode(button.dataset.sourceMode));
    });
    document.getElementById("spotify-connect-button")?.addEventListener("click", connectSpotify);

    consumeSpotifyCallbackMessage();
    loadSourceStatus();
    startSourcePolling();
});

document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        stopSourcePolling();
        return;
    }
    loadSourceStatus();
    startSourcePolling();
});
