const CURRENT_TRACK = {
    artist: "",
    title: "",
    album: "",
    genre: "",
    coverUrl: "",
    trackId: "",
    artistId: "",
    durationMs: null,
};

let statusInterval = null;
let recognizerInterval = null;

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

function updateCurrentTrack(status) {
    CURRENT_TRACK.artist = status.artist || "";
    CURRENT_TRACK.title = status.title || "";
    CURRENT_TRACK.album = status.album || "";
    CURRENT_TRACK.genre = status.genre || "";
    CURRENT_TRACK.coverUrl = status.cover_url || "";
    CURRENT_TRACK.trackId = status.track_id || "";
    CURRENT_TRACK.artistId = status.artist_id || "";
    CURRENT_TRACK.durationMs = status.duration_ms || null;
}

function renderEmptyStatus(message = "No recognized song yet") {
    setText("song-artist", "");
    setText("song-title", message);
    setText("song-album", "");
    setText("song-genre", "");

    const genre = document.getElementById("song-genre");
    if (genre) genre.classList.add("hidden");

    const cover = document.getElementById("song-cover");
    if (cover) cover.src = "/logo.png";

    const songCard = document.querySelector(".song-card");
    if (songCard) songCard.style.setProperty("--song-bg", "#2b2b34");
}

function renderStatus(status) {
    updateCurrentTrack(status);

    setText("song-artist", CURRENT_TRACK.artist || "Unknown artist");
    setText("song-title", CURRENT_TRACK.title || "Unknown title");
    setText("song-album", CURRENT_TRACK.album);

    const genre = document.getElementById("song-genre");
    if (genre) {
        genre.textContent = CURRENT_TRACK.genre;
        genre.classList.toggle("hidden", !CURRENT_TRACK.genre);
    }

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
    if (!artist || !title) {
        box.textContent = "No track information available.";
        return;
    }

    try {
        const response = await fetch(
            `/api/lyrics?artist=${encodeURIComponent(artist)}&title=${encodeURIComponent(title)}`,
            { cache: "no-store" },
        );
        const result = await response.json();

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
        console.error(error);
        box.textContent = "Error loading lyrics.";
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

    content.replaceChildren(songBlock, artistBlock);
}

async function showTrackInfo() {
    const content = document.getElementById("track-info-content");
    openTrackInfoDrawer();
    if (content) content.textContent = "Loading Shazam info…";

    if (!CURRENT_TRACK.trackId && !CURRENT_TRACK.artistId) {
        renderTrackInfo();
        return;
    }

    try {
        const params = new URLSearchParams();
        if (CURRENT_TRACK.trackId) params.set("track_id", CURRENT_TRACK.trackId);
        if (CURRENT_TRACK.artistId) params.set("artist_id", CURRENT_TRACK.artistId);

        const response = await fetch(`/api/shazam/info?${params.toString()}`, { cache: "no-store" });
        const data = await response.json();
        renderTrackInfo(response.ok && data.ok ? data : {});
    } catch (error) {
        console.error(error);
        renderTrackInfo();
    }
}

function startPolling() {
    if (!statusInterval) statusInterval = window.setInterval(loadStatus, 15000);
    if (!recognizerInterval) recognizerInterval = window.setInterval(loadRecognizerStatus, 15000);
}

function stopPolling() {
    if (statusInterval) window.clearInterval(statusInterval);
    if (recognizerInterval) window.clearInterval(recognizerInterval);
    statusInterval = null;
    recognizerInterval = null;
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
    startPolling();
});

document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        stopPolling();
        return;
    }

    loadStatus();
    loadRecognizerStatus();
    startPolling();
});
