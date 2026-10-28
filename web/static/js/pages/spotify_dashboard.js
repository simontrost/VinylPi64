/* Source selector + Spotify dashboard behavior. Loaded after dashboard.js. */

let vinylPiSourceMode = "off";
let vinylPiSourcePollTimer = null;
let vinylPiSourceRequestId = 0;
let vinylPiSourceChanging = false;
let vinylPiLastSourceData = null;

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

function hideDiscogsForNonVinyl() {
    document.getElementById("discogs-context")?.classList.add("hidden");
    document.getElementById("discogs-add-link")?.classList.add("hidden");
    document.getElementById("discogs-side-flip")?.classList.add("hidden");
}

renderDiscogsContext = function renderDiscogsContextWithSource() {
    if (vinylPiSourceMode !== "vinyl") {
        hideDiscogsForNonVinyl();
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
    const trackUrl = CURRENT_TRACK.spotifyUrl
        || (CURRENT_TRACK.trackId && !String(CURRENT_TRACK.trackId).startsWith("local:")
            ? `https://open.spotify.com/track/${encodeURIComponent(CURRENT_TRACK.trackId)}`
            : "");
    appendInfoLink(songBlock, "Open track in Spotify", trackUrl);

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
    const shouldShow = true
        && vinylPiSourceMode === "spotify"
        && (!configured || !connected);
    row.classList.toggle("hidden", !shouldShow);
    if (!shouldShow) return;

    if (!configured) {
        copy.textContent = "Spotify app credentials are missing in vinylpi.env.";
        button.classList.add("hidden");
        return;
    }

    copy.textContent = "This device is not connected to Spotify yet.";
    button.classList.remove("hidden");
    button.textContent = "Connect Spotify";
}

function updateSourceUI(data = {}) {
    vinylPiLastSourceData = data;
    vinylPiSourceMode = ["off", "vinyl", "spotify"].includes(data.mode) ? data.mode : "off";
    try {
        document.dispatchEvent(new CustomEvent("vinylpi:source-change", { detail: { mode: vinylPiSourceMode } }));
    } catch (error) {
        console.error("Source-change UI listener failed:", error);
    }

    document.querySelectorAll("[data-source-mode]").forEach((button) => {
        const active = button.dataset.sourceMode === vinylPiSourceMode;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
        button.disabled = false;
    });

    renderSpotifyConnection(data.spotify || {});

    const infoLabel = document.querySelector(".track-info-label");
    if (infoLabel) infoLabel.textContent = vinylPiSourceMode === "spotify" ? "Spotify Info" : "Shazam Info";

    const actions = document.querySelector(".song-actions");
    actions?.classList.toggle("hidden", vinylPiSourceMode === "off");

    if (vinylPiSourceMode !== "vinyl") {
        hideDiscogsForNonVinyl();
    } else if (currentTrackKey) {
        vinylPiOriginalRenderDiscogsContext();
    }

    if (vinylPiSourceMode === "spotify" && currentTrackKey) {
        setText("now-playing-label", "Spotify");
    }
}

async function loadSourceStatus() {
    const requestId = ++vinylPiSourceRequestId;
    try {
        const response = await fetch("/api/source", { cache: "no-store" });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || `Source request failed: ${response.status}`);
        if (requestId !== vinylPiSourceRequestId || vinylPiSourceChanging) return;
        updateSourceUI(data);
        // Don't erase real authorization or configuration errors on each poll.
    } catch (error) {
        console.error(error);
    }
}

async function setSourceMode(mode) {
    vinylPiSourceChanging = true;
    ++vinylPiSourceRequestId;
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
        if (!response.ok || !data.ok) {
            const reason = data.needs_auth ? "Connect Spotify first."
                : data.needs_config ? "Add Spotify app credentials to vinylpi.env first."
                : data.error || "Source switch rejected. Check Logs.";
            throw new Error(reason);
        }
        updateSourceUI(data);
        setSpotifyFeedback("");
    } catch (error) {
        console.error("Source switch request failed:", error);
        // A successful backend switch can outlive a failed response. Confirm
        // actual mode before presenting an error; never show a phantom failure.
        try {
            const current = await fetch("/api/source", { cache: "no-store" });
            const currentData = await current.json();
            if (current.ok && currentData.ok && currentData.mode === mode) {
                updateSourceUI(currentData);
                setSpotifyFeedback("");
            } else {
                setSpotifyFeedback(error?.message || "Source switch failed. Check Logs.", "error");
            }
        } catch (readError) {
            console.error("Could not confirm current source:", readError);
            setSpotifyFeedback("Source status unavailable. Check Logs.", "error");
        }
    } finally {
        vinylPiSourceChanging = false;
        document.querySelectorAll("[data-source-mode]").forEach((button) => {
            button.disabled = false;
        });
        await loadSourceStatus();
        await loadStatus();
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

// The track card and selector must commit the same source from the same
// /api/status event, rather than diverge until the next /api/source poll.
document.addEventListener("vinylpi:visible-status", (event) => {
    if (vinylPiSourceChanging) return;
    const mode = event.detail?.mode;
    if (!["off", "vinyl", "spotify"].includes(mode) || mode === vinylPiSourceMode) return;
    vinylPiSourceMode = mode;
    document.querySelectorAll("[data-source-mode]").forEach((button) => {
        const active = button.dataset.sourceMode === mode;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
    });
    // Refresh additional connection data without delaying the selector.
    loadSourceStatus();
});
