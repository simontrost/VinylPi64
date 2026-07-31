const CURRENT_TRACK = {
    artist: "",
    title: "",
    album: "",
    genre: "",
    coverUrl: "",
    trackId: "",
    artistId: "",
    durationMs: null,
    discogsReleaseId: null,
    discogsPosition: "",
    discogsSide: "",
    discogsTrackIndex: null,
    discogsTrackCount: null,
    discogsSideTrackNumber: null,
    discogsSideTrackCount: null,
    discogsMatchSource: "",
    discogsConfidence: null,
    discogsCoverUrl: "",
    discogsYear: null,
    discogsLabel: "",
    discogsCatalogNumber: "",
    discogsExpectedNextTitle: "",
    discogsExpectedNextArtist: "",
    discogsExpectedNextPosition: "",
    discogsExpectedNextSide: "",
};

let statusInterval = null;
let recognizerInterval = null;
let currentTrackKey = "";
let lyricsAbortController = null;
let trackInfoAbortController = null;
let statusEventSource = null;

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
}

function formatDuration(durationMs) {
    const milliseconds = Number(durationMs);
    if (!Number.isFinite(milliseconds) || milliseconds <= 0) return "";

    const totalSeconds = Math.round(milliseconds / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = String(totalSeconds % 60).padStart(2, "0");
    return `${minutes}:${seconds}`;
}

function getTrackKey(track = CURRENT_TRACK) {
    const trackId = String(track.trackId || track.track_id || "").trim();
    if (trackId) return `id:${trackId}`;

    const artist = String(track.artist || "").trim().toLocaleLowerCase();
    const title = String(track.title || "").trim().toLocaleLowerCase();
    return artist || title ? `text:${artist}|${title}` : "";
}

function resetTrackDependentUI() {
    lyricsAbortController?.abort();
    lyricsAbortController = null;

    trackInfoAbortController?.abort();
    trackInfoAbortController = null;

    const lyricsBox = document.getElementById("lyrics-box");
    if (lyricsBox) {
        lyricsBox.textContent = "";
        lyricsBox.classList.add("hidden", "collapsed");
    }

    const lyricsToggle = document.getElementById("btn-lyrics-toggle");
    if (lyricsToggle) {
        lyricsToggle.classList.add("hidden");
        lyricsToggle.textContent = "More";
    }

    document.getElementById("lyrics-card")?.classList.remove("expanded");
    closeTrackInfoDrawer();

    const infoContent = document.getElementById("track-info-content");
    if (infoContent) infoContent.textContent = "No data loaded.";
    setText("track-info-heading", "Track Info");
}

function updateCurrentTrack(status) {
    CURRENT_TRACK.artist = status.artist || "";
    CURRENT_TRACK.title = status.title || "";
    CURRENT_TRACK.album = status.album || "";
    CURRENT_TRACK.genre = status.genre || "";
    CURRENT_TRACK.coverUrl = status.cover_url || "";
    CURRENT_TRACK.trackId = status.track_id || "";
    CURRENT_TRACK.artistId = status.artist_id || "";
    CURRENT_TRACK.durationMs = status.duration_ms || null;
    CURRENT_TRACK.discogsReleaseId = status.discogs_release_id || null;
    CURRENT_TRACK.discogsPosition = status.discogs_position || "";
    CURRENT_TRACK.discogsSide = status.discogs_side || "";
    CURRENT_TRACK.discogsTrackIndex = Number.isInteger(status.discogs_track_index) ? status.discogs_track_index : null;
    CURRENT_TRACK.discogsTrackCount = status.discogs_track_count || null;
    CURRENT_TRACK.discogsSideTrackNumber = status.discogs_side_track_number || null;
    CURRENT_TRACK.discogsSideTrackCount = status.discogs_side_track_count || null;
    CURRENT_TRACK.discogsMatchSource = status.discogs_match_source || "";
    CURRENT_TRACK.discogsConfidence = status.discogs_confidence ?? null;
    CURRENT_TRACK.discogsCoverUrl = status.discogs_cover_url || "";
    CURRENT_TRACK.discogsYear = status.discogs_year || null;
    CURRENT_TRACK.discogsLabel = status.discogs_label || "";
    CURRENT_TRACK.discogsCatalogNumber = status.discogs_catalog_number || "";
    CURRENT_TRACK.discogsExpectedNextTitle = status.discogs_expected_next_title || "";
    CURRENT_TRACK.discogsExpectedNextArtist = status.discogs_expected_next_artist || "";
    CURRENT_TRACK.discogsExpectedNextPosition = status.discogs_expected_next_position || "";
    CURRENT_TRACK.discogsExpectedNextSide = status.discogs_expected_next_side || "";
}

function renderDiscogsContext() {
    const context = document.getElementById("discogs-context");
    if (!context) return;

    const matched = Boolean(CURRENT_TRACK.discogsReleaseId);
    context.classList.toggle("hidden", !matched);
    if (!matched) return;

    const confidence = Number(CURRENT_TRACK.discogsConfidence);
    const confidenceLabel = Number.isFinite(confidence)
        ? `${Math.round(confidence * 100)}%`
        : "";
    const sourceLabel = CURRENT_TRACK.discogsMatchSource === "sequence_inferred"
        ? "Sequence estimate"
        : (CURRENT_TRACK.discogsMatchSource === "sequence" ? "Sequence match" : "Collection match");
    setText("discogs-match-label", [sourceLabel, confidenceLabel].filter(Boolean).join(" · "));
    setText("discogs-position", CURRENT_TRACK.discogsPosition || "Collection");

    const progressParts = [];
    if (CURRENT_TRACK.discogsSide) progressParts.push(`Side ${CURRENT_TRACK.discogsSide}`);
    if (CURRENT_TRACK.discogsSideTrackNumber && CURRENT_TRACK.discogsSideTrackCount) {
        progressParts.push(`track ${CURRENT_TRACK.discogsSideTrackNumber} of ${CURRENT_TRACK.discogsSideTrackCount}`);
    } else if (CURRENT_TRACK.discogsTrackIndex !== null && CURRENT_TRACK.discogsTrackCount) {
        progressParts.push(`track ${CURRENT_TRACK.discogsTrackIndex + 1} of ${CURRENT_TRACK.discogsTrackCount}`);
    }
    setText("discogs-track-progress", progressParts.join(" · "));

    const next = document.getElementById("discogs-next-track");
    if (!next) return;
    if (CURRENT_TRACK.discogsExpectedNextTitle) {
        const nextPosition = CURRENT_TRACK.discogsExpectedNextPosition
            ? `${CURRENT_TRACK.discogsExpectedNextPosition} · `
            : "";
        const sideChange = CURRENT_TRACK.discogsExpectedNextSide
            && CURRENT_TRACK.discogsSide
            && CURRENT_TRACK.discogsExpectedNextSide !== CURRENT_TRACK.discogsSide;
        next.textContent = `${sideChange ? "Next side" : "Next"}: ${nextPosition}${CURRENT_TRACK.discogsExpectedNextTitle}`;
        next.classList.remove("hidden");
    } else {
        next.textContent = "End of release";
        next.classList.remove("hidden");
    }
}

function renderEmptyStatus(message = "No recognized song yet") {
    setText("now-playing-label", "Now playing");
    setText("song-artist", "");
    setText("song-title", message);
    setText("song-album", "");
    setText("song-genre", "");

    const genre = document.getElementById("song-genre");
    if (genre) genre.classList.add("hidden");

    const cover = document.getElementById("song-cover");
    if (cover) cover.src = "/logo.png";

    document.getElementById("discogs-context")?.classList.add("hidden");

    const songCard = document.querySelector(".song-card");
    if (songCard) songCard.style.setProperty("--song-bg", "#2b2b34");
}

function renderStatus(status) {
    const nextTrackKey = getTrackKey({
        artist: status.artist,
        title: status.title,
        track_id: status.track_id,
    });
    const trackChanged = Boolean(currentTrackKey && nextTrackKey && currentTrackKey !== nextTrackKey);

    if (trackChanged) resetTrackDependentUI();

    updateCurrentTrack(status);
    currentTrackKey = getTrackKey();

    setText(
        "now-playing-label",
        CURRENT_TRACK.discogsMatchSource === "sequence_inferred" ? "Likely playing" : "Now playing",
    );
    setText("song-artist", CURRENT_TRACK.artist || "Unknown artist");
    setText("song-title", CURRENT_TRACK.title || "Unknown title");
    setText("song-album", CURRENT_TRACK.album);

    const genre = document.getElementById("song-genre");
    if (genre) {
        genre.textContent = CURRENT_TRACK.genre;
        genre.classList.toggle("hidden", !CURRENT_TRACK.genre);
    }

    renderDiscogsContext();

    const cover = document.getElementById("song-cover");
    if (cover) {
        cover.src = CURRENT_TRACK.coverUrl || "/logo.png";
        cover.onerror = () => {
            cover.onerror = null;
            cover.src = "/logo.png";
        };
    }

    const songCard = document.querySelector(".song-card");
    if (songCard) songCard.style.setProperty("--song-bg", status.bg_color || "#2b2b34");
}

async function loadStatus() {
    try {
        const response = await fetch("/api/status", { cache: "no-store" });
        if (!response.ok) throw new Error(`Status request failed: ${response.status}`);

        const status = await response.json();
        if (!status || status.status === null || status.error) {
            renderEmptyStatus();
            return;
        }

        renderStatus(status);
    } catch (error) {
        console.error(error);
        renderEmptyStatus("Error loading track status");
    }
}

async function loadRecognizerStatus() {
    const statusElement = document.getElementById("rec-status-text");
    const toggle = document.getElementById("recognizerToggle");
    if (!statusElement || !toggle) return;

    try {
        const response = await fetch("/api/recognizer/status", { cache: "no-store" });
        if (!response.ok) throw new Error(`Recognizer request failed: ${response.status}`);

        const data = await response.json();
        const running = Boolean(data.running);
        toggle.checked = running;
        statusElement.classList.toggle("rec-status-running", running);
        statusElement.classList.toggle("rec-status-stopped", !running);
        statusElement.textContent = running ? "Running" : "Stopped";
    } catch (error) {
        console.error(error);
        statusElement.classList.remove("rec-status-running", "rec-status-stopped");
        statusElement.textContent = "Status unavailable";
    }
}

async function setRecognizerRunning(shouldRun) {
    const toggle = document.getElementById("recognizerToggle");
    const statusElement = document.getElementById("rec-status-text");
    if (!toggle || !statusElement) return;

    toggle.disabled = true;
    statusElement.textContent = "Changing status…";

    try {
        const endpoint = shouldRun ? "/api/recognizer/start" : "/api/recognizer/stop";
        const response = await fetch(endpoint, { method: "POST" });
        if (!response.ok) throw new Error(`Recognizer update failed: ${response.status}`);
    } catch (error) {
        console.error(error);
    } finally {
        await loadRecognizerStatus();
        toggle.disabled = false;
    }
}

async function loadLyrics() {
    const box = document.getElementById("lyrics-box");
    const toggleButton = document.getElementById("btn-lyrics-toggle");
    const card = document.getElementById("lyrics-card");
    if (!box || !toggleButton) return;

    box.classList.remove("hidden");
    box.classList.add("collapsed");
    box.textContent = "Loading lyrics…";
    toggleButton.classList.add("hidden");
    if (card) card.classList.remove("expanded");

    const artist = CURRENT_TRACK.artist.trim();
    const title = CURRENT_TRACK.title.trim();
    const requestedTrackKey = getTrackKey();
    if (!artist || !title) {
        box.textContent = "No track information available.";
        return;
    }

    lyricsAbortController?.abort();
    const controller = new AbortController();
    lyricsAbortController = controller;

    try {
        const response = await fetch(
            `/api/lyrics?artist=${encodeURIComponent(artist)}&title=${encodeURIComponent(title)}`,
            { cache: "no-store", signal: controller.signal },
        );
        const result = await response.json();

        if (requestedTrackKey !== getTrackKey()) return;

        if (!response.ok || !result.ok || !result.lyrics) {
            box.textContent = "No lyrics found. Opening Genius search…";
            window.open(
                `https://genius.com/search?q=${encodeURIComponent(`${artist} ${title}`)}`,
                "_blank",
                "noopener,noreferrer",
            );
            return;
        }

        box.textContent = result.lyrics;
        toggleButton.classList.remove("hidden");
        toggleButton.textContent = "More";
    } catch (error) {
        if (error.name === "AbortError") return;
        console.error(error);
        if (requestedTrackKey === getTrackKey()) box.textContent = "Error loading lyrics.";
    } finally {
        if (lyricsAbortController === controller) lyricsAbortController = null;
    }
}

function openTrackInfoDrawer() {
    document.getElementById("track-info-drawer")?.classList.add("open");
    document.getElementById("info-backdrop")?.classList.remove("hidden");
}

function closeTrackInfoDrawer() {
    document.getElementById("track-info-drawer")?.classList.remove("open");
    document.getElementById("info-backdrop")?.classList.add("hidden");
}

function findFirstUrl(value, visited = new WeakSet()) {
    if (!value || typeof value !== "object") return "";
    if (visited.has(value)) return "";
    visited.add(value);

    for (const key of ["url", "href", "sharehref", "weburl"]) {
        if (typeof value[key] === "string" && value[key].startsWith("http")) return value[key];
    }

    for (const nested of Object.values(value)) {
        if (typeof nested === "string" && nested.startsWith("http")) return nested;
        if (nested && typeof nested === "object") {
            const result = findFirstUrl(nested, visited);
            if (result) return result;
        }
    }
    return "";
}

function extractTrackDetails(data) {
    const track = data?.track || {};
    const primaryGenre = track.genres?.primary;
    return {
        title: track.title || track.heading?.title || CURRENT_TRACK.title,
        artist: track.subtitle || track.heading?.subtitle || CURRENT_TRACK.artist,
        album: CURRENT_TRACK.album,
        genre: Array.isArray(primaryGenre) ? primaryGenre.join(", ") : (primaryGenre || CURRENT_TRACK.genre),
        url: findFirstUrl(track),
    };
}

function extractArtistDetails(data) {
    const artist = data?.artist || {};
    return {
        name: artist.name || artist.data?.attributes?.name || CURRENT_TRACK.artist,
        url: findFirstUrl(artist),
    };
}

function appendInfoRow(container, label, value) {
    if (!value) return;
    const row = document.createElement("div");
    row.className = "track-info-row";

    const strong = document.createElement("strong");
    strong.textContent = `${label}: `;
    row.append(strong, document.createTextNode(String(value)));
    container.appendChild(row);
}

function appendInfoLink(container, label, url) {
    if (!url) return;
    const row = document.createElement("div");
    row.className = "track-info-row";

    const link = document.createElement("a");
    link.className = "track-info-link";
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = label;

    row.appendChild(link);
    container.appendChild(row);
}

function createInfoBlock(title) {
    const block = document.createElement("section");
    block.className = "track-info-block";
    const heading = document.createElement("h3");
    heading.textContent = title;
    block.appendChild(heading);
    return block;
}

function renderTrackInfo(data = {}) {
    const content = document.getElementById("track-info-content");
    if (!content) return;

    const track = extractTrackDetails(data);
    const artist = extractArtistDetails(data);
    setText("track-info-heading", track.title || "Track Info");

    const songBlock = createInfoBlock("Song");
    appendInfoRow(songBlock, "Title", track.title || "Unknown");
    appendInfoRow(songBlock, "Artist", track.artist || "Unknown");
    appendInfoRow(songBlock, "Album", track.album || "Unknown");
    appendInfoRow(songBlock, "Genre", track.genre);
    appendInfoRow(songBlock, "Duration", formatDuration(CURRENT_TRACK.durationMs));
    appendInfoRow(songBlock, "Shazam track ID", CURRENT_TRACK.trackId);
    appendInfoLink(songBlock, "Open Shazam track", track.url);

    const artistBlock = createInfoBlock("Artist");
    appendInfoRow(artistBlock, "Name", artist.name || "Unknown");
    appendInfoRow(artistBlock, "Shazam artist ID", CURRENT_TRACK.artistId);
    appendInfoLink(artistBlock, "Open Shazam artist", artist.url);

    const blocks = [songBlock, artistBlock];
    if (CURRENT_TRACK.discogsReleaseId) {
        const discogsBlock = createInfoBlock("Discogs collection");
        appendInfoRow(discogsBlock, "Position", CURRENT_TRACK.discogsPosition);
        appendInfoRow(discogsBlock, "Side", CURRENT_TRACK.discogsSide);
        appendInfoRow(discogsBlock, "Year", CURRENT_TRACK.discogsYear);
        appendInfoRow(discogsBlock, "Label", CURRENT_TRACK.discogsLabel);
        appendInfoRow(discogsBlock, "Catalog number", CURRENT_TRACK.discogsCatalogNumber);
        appendInfoRow(
            discogsBlock,
            "Match",
            `${CURRENT_TRACK.discogsMatchSource === "sequence_inferred" ? "Sequence estimate" : (CURRENT_TRACK.discogsMatchSource === "sequence" ? "Record sequence" : "Collection")}${CURRENT_TRACK.discogsConfidence !== null ? ` (${Math.round(Number(CURRENT_TRACK.discogsConfidence) * 100)}%)` : ""}`,
        );
        appendInfoLink(
            discogsBlock,
            "Open Discogs release",
            `https://www.discogs.com/release/${CURRENT_TRACK.discogsReleaseId}`,
        );
        blocks.push(discogsBlock);
    }

    content.replaceChildren(...blocks);
}

async function showTrackInfo() {
    const content = document.getElementById("track-info-content");
    const requestedTrackKey = getTrackKey();
    openTrackInfoDrawer();
    if (content) content.textContent = "Loading Shazam info…";

    if (!CURRENT_TRACK.trackId && !CURRENT_TRACK.artistId) {
        renderTrackInfo();
        return;
    }

    trackInfoAbortController?.abort();
    const controller = new AbortController();
    trackInfoAbortController = controller;

    try {
        const params = new URLSearchParams();
        if (CURRENT_TRACK.trackId) params.set("track_id", CURRENT_TRACK.trackId);
        if (CURRENT_TRACK.artistId) params.set("artist_id", CURRENT_TRACK.artistId);

        const response = await fetch(`/api/shazam/info?${params.toString()}`, {
            cache: "no-store",
            signal: controller.signal,
        });
        const data = await response.json();
        if (requestedTrackKey !== getTrackKey()) return;
        renderTrackInfo(response.ok && data.ok ? data : {});
    } catch (error) {
        if (error.name === "AbortError") return;
        console.error(error);
        if (requestedTrackKey === getTrackKey()) renderTrackInfo();
    } finally {
        if (trackInfoAbortController === controller) trackInfoAbortController = null;
    }
}

function startStatusFallbackPolling() {
    if (!statusInterval) statusInterval = window.setInterval(loadStatus, 2000);
}

function stopStatusFallbackPolling() {
    if (statusInterval) window.clearInterval(statusInterval);
    statusInterval = null;
}

function startRecognizerPolling() {
    if (!recognizerInterval) recognizerInterval = window.setInterval(loadRecognizerStatus, 5000);
}

function stopRecognizerPolling() {
    if (recognizerInterval) window.clearInterval(recognizerInterval);
    recognizerInterval = null;
}

function connectStatusEvents() {
    if (statusEventSource || typeof EventSource === "undefined") {
        if (typeof EventSource === "undefined") startStatusFallbackPolling();
        return;
    }

    statusEventSource = new EventSource("/api/events");
    statusEventSource.addEventListener("open", () => {
        stopStatusFallbackPolling();
    });
    statusEventSource.addEventListener("status", (event) => {
        try {
            const status = JSON.parse(event.data);
            if (!status || status.status === null || status.error) {
                renderEmptyStatus();
                return;
            }
            renderStatus(status);
        } catch (error) {
            console.error("Invalid status event", error);
        }
    });
    statusEventSource.addEventListener("error", () => {
        startStatusFallbackPolling();
    });
}

function disconnectStatusEvents() {
    statusEventSource?.close();
    statusEventSource = null;
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("recognizerToggle")?.addEventListener("change", (event) => {
        setRecognizerRunning(event.target.checked);
    });
    document.getElementById("btn-lyrics")?.addEventListener("click", loadLyrics);
    document.getElementById("btn-track-info")?.addEventListener("click", showTrackInfo);
    document.getElementById("btn-track-info-close")?.addEventListener("click", closeTrackInfoDrawer);
    document.getElementById("info-backdrop")?.addEventListener("click", closeTrackInfoDrawer);

    document.getElementById("btn-lyrics-toggle")?.addEventListener("click", () => {
        const box = document.getElementById("lyrics-box");
        const card = document.getElementById("lyrics-card");
        const button = document.getElementById("btn-lyrics-toggle");
        if (!box || !button) return;

        const collapsed = box.classList.toggle("collapsed");
        card?.classList.toggle("expanded", !collapsed);
        button.textContent = collapsed ? "More" : "Less";
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeTrackInfoDrawer();
    });

    loadStatus();
    loadRecognizerStatus();
    connectStatusEvents();
    startRecognizerPolling();
});

document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        disconnectStatusEvents();
        stopStatusFallbackPolling();
        stopRecognizerPolling();
        return;
    }

    loadStatus();
    loadRecognizerStatus();
    connectStatusEvents();
    startRecognizerPolling();
});
