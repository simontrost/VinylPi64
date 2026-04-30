let CURRENT_TRACK = {
    artist: "",
    title: "",
    album: "",
    track_id: "",
    artist_id: "",
};

async function loadStatus() {
    try {
        const r = await fetch("/api/status");
        const st = await r.json();

        const titleEl = document.getElementById("song-title");
        const artistEl = document.getElementById("song-artist");
        const albumEl = document.getElementById("song-album");
        const coverEl = document.getElementById("song-cover");

        if (st.error) {
            titleEl.innerText = "No data";
            artistEl.innerText = "";
            albumEl.innerText = "";
            coverEl.src = "/logo.png";
            const songCard = document.querySelector(".song-card");
            if (songCard) {
                songCard.style.setProperty("--song-bg", "#2b2b2b");
            }
            return;
        }

        const title = st.title || "Unknown title";
        const artist = st.artist || "Unknown artist";
        const album = st.album || "";

        artistEl.innerText = artist;
        titleEl.innerText = title;
        albumEl.innerText = album ? `${album}` : "";

        coverEl.src = st.cover_url || "/logo.png";
        const songCard = document.querySelector(".song-card");
        if (songCard) {
            songCard.style.setProperty("--song-bg", st.bg_color || "#2b2b2b");
        }

        CURRENT_TRACK.artist = artist;
        CURRENT_TRACK.title = title;
        CURRENT_TRACK.album = album;
        CURRENT_TRACK.track_id = st.track_id || "";
        CURRENT_TRACK.artist_id = st.artist_id || "";

    } catch (e) {
        console.error(e);
        document.getElementById("song-title").innerText = "Error loading data";
    }
}

async function loadRecognizerStatus() {
    const statusEl = document.getElementById("rec-status-text");
    const toggle = document.getElementById("recognizerToggle");
    if (!statusEl || !toggle) return;

    try {
        const r = await fetch("/api/recognizer/status");
        const data = await r.json();

        const running = !!data.running;
        toggle.checked = running;

        statusEl.classList.remove("rec-status-running", "rec-status-stopped");

        if (running) {
            statusEl.textContent = "Running";
            statusEl.classList.add("rec-status-running");
        } else {
            statusEl.textContent = "Stopped";
            statusEl.classList.add("rec-status-stopped");
        }
    } catch (e) {
        console.error(e);
        statusEl.textContent = "Status error";
        statusEl.classList.remove("rec-status-running", "rec-status-stopped");
    }
}

async function showLyrics() {
    const r = await fetch("/api/status");
    const st = await r.json();

    const artist = st.artist;
    const title = st.title;

    const lr = await fetch(`/api/lyrics?artist=${encodeURIComponent(artist)}&title=${encodeURIComponent(title)}`);
    const res = await lr.json();

    if (!res.ok) {
        window.open(`https://genius.com/search?q=${encodeURIComponent(artist + " " + title)}`);
        return;
    }

    document.getElementById("lyrics-box").innerText = res.lyrics;
}

function openTrackInfoDrawer() {
    const drawer = document.getElementById("track-info-drawer");
    const backdrop = document.getElementById("info-backdrop");

    if (drawer) drawer.classList.add("open");
    if (backdrop) backdrop.classList.remove("hidden");
}

function closeTrackInfoDrawer() {
    const drawer = document.getElementById("track-info-drawer");
    const backdrop = document.getElementById("info-backdrop");

    if (drawer) drawer.classList.remove("open");
    if (backdrop) backdrop.classList.add("hidden");
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function findFirstUrl(obj) {
    if (!obj || typeof obj !== "object") return "";

    const directKeys = ["url", "href", "sharehref", "weburl"];
    for (const key of directKeys) {
        if (typeof obj[key] === "string" && obj[key].startsWith("http")) {
            return obj[key];
        }
    }

    for (const value of Object.values(obj)) {
        if (typeof value === "string" && value.startsWith("http")) {
            return value;
        }
        if (value && typeof value === "object") {
            const nested = findFirstUrl(value);
            if (nested) return nested;
        }
    }

    return "";
}

function pickTrackInfo(data) {
    const track = data?.track || {};

    return {
        title:
            track.title ||
            track.heading?.title ||
            CURRENT_TRACK.title,
        artist:
            track.subtitle ||
            track.heading?.subtitle ||
            CURRENT_TRACK.artist,
        album:
            CURRENT_TRACK.album,
        genres:
            Array.isArray(track.genres?.primary)
                ? track.genres.primary.join(", ")
                : (track.genres?.primary || ""),
        url: findFirstUrl(track),
    };
}

function pickArtistInfo(data) {
    const artist = data?.artist || {};

    return {
        name:
            artist.name ||
            artist.data?.attributes?.name ||
            CURRENT_TRACK.artist,
        url: findFirstUrl(artist),
    };
}

function renderTrackInfo(data) {
    const content = document.getElementById("track-info-content");
    const heading = document.getElementById("track-info-heading");

    const track = pickTrackInfo(data);
    const artist = pickArtistInfo(data);

    if (heading) {
        heading.textContent = track.title || "Track Info";
    }

    const trackUrl = track.url
        ? `<div class="track-info-row"><a class="track-info-link" href="${escapeHtml(track.url)}" target="_blank" rel="noopener noreferrer">Shazam Track öffnen</a></div>`
        : "";

    const artistUrl = artist.url
        ? `<div class="track-info-row"><a class="track-info-link" href="${escapeHtml(artist.url)}" target="_blank" rel="noopener noreferrer">Shazam Artist öffnen</a></div>`
        : "";

    content.innerHTML = `
        <div class="track-info-block">
            <h3>Song</h3>
            <div class="track-info-row"><strong>Titel:</strong> ${escapeHtml(track.title || "Unbekannt")}</div>
            <div class="track-info-row"><strong>Artist:</strong> ${escapeHtml(track.artist || "Unbekannt")}</div>
            <div class="track-info-row"><strong>Album:</strong> ${escapeHtml(track.album || "Unbekannt")}</div>
            ${track.genres ? `<div class="track-info-row"><strong>Genre:</strong> ${escapeHtml(track.genres)}</div>` : ""}
            ${trackUrl}
        </div>

        <div class="track-info-block">
            <h3>Artist</h3>
            <div class="track-info-row"><strong>Name:</strong> ${escapeHtml(artist.name || CURRENT_TRACK.artist || "Unbekannt")}</div>
            ${artistUrl}
        </div>
    `;
}

async function showTrackInfo() {
    const content = document.getElementById("track-info-content");

    openTrackInfoDrawer();

    if (content) {
        content.textContent = "Loading Shazam info...";
    }

    const trackId = CURRENT_TRACK.track_id;
    const artistId = CURRENT_TRACK.artist_id;

    if (!trackId && !artistId) {
        if (content) {
            content.textContent = "Für diesen Song sind keine Shazam-IDs gespeichert. Warte auf die nächste Erkennung oder prüfe /api/status.";
        }
        return;
    }

    try {
        const url =
            `/api/shazam/info?track_id=${encodeURIComponent(trackId)}&artist_id=${encodeURIComponent(artistId)}`;

        const r = await fetch(url);
        const data = await r.json();

        if (!data.ok) {
            if (content) {
                content.textContent = `Keine Shazam-Infos gefunden: ${data.error || "unknown error"}`;
            }
            return;
        }

        renderTrackInfo(data);

    } catch (e) {
        console.error(e);
        if (content) {
            content.textContent = "Error loading Shazam info.";
        }
    }
}

async function setRecognizerRunning(shouldRun) {
    const toggle = document.getElementById("recognizerToggle");
    const statusEl = document.getElementById("rec-status-text");
    if (!toggle || !statusEl) return;

    toggle.disabled = true;
    statusEl.textContent = "Changing status...";

    try {
        const url = shouldRun ? "/api/recognizer/start" : "/api/recognizer/stop";
        await fetch(url, { method: "POST" });
    } catch (e) {
        console.error(e);
    }

    await loadRecognizerStatus();
    toggle.disabled = false;
}

let statusInterval = null;
let recInterval = null;

document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.getElementById("recognizerToggle");
    if (toggle) {
        toggle.addEventListener("change", (e) => {
            setRecognizerRunning(e.target.checked);
        });
    }

    loadStatus();
    loadRecognizerStatus();

    statusInterval = setInterval(loadStatus, 15000);
    recInterval = setInterval(loadRecognizerStatus, 15000);

    const btnLyrics = document.getElementById("btn-lyrics");
    const btnToggle = document.getElementById("btn-lyrics-toggle");
    const box = document.getElementById("lyrics-box");

    if (btnLyrics && btnToggle && box) {
        btnLyrics.addEventListener("click", async () => {
            box.classList.remove("hidden");
            box.textContent = "Loading lyrics...";

            const artist = (CURRENT_TRACK.artist || "").trim();
            const title = (CURRENT_TRACK.title || "").trim();

            if (!artist || !title) {
                box.textContent = "No track information available.";
                return;
            }

            try {
                const lr = await fetch(
                    `/api/lyrics?artist=${encodeURIComponent(artist)}&title=${encodeURIComponent(title)}`
                );
                const res = await lr.json();

                if (!res.ok || !res.lyrics) {
                    box.textContent = "No lyrics found. Opening Genius...";
                    window.open(
                        `https://genius.com/search?q=${encodeURIComponent(artist + " " + title)}`,
                        "_blank",
                        "noopener,noreferrer"
                    );
                    return;
                }

                box.textContent = res.lyrics;

                box.classList.add("collapsed");
                btnToggle.classList.remove("hidden");
                btnToggle.textContent = "More";

                const card = document.getElementById("lyrics-card");
                if (card) card.classList.remove("expanded");

            } catch (e) {
                console.error(e);
                box.textContent = "Error loading lyrics.";
            }
        });

        const card = document.getElementById("lyrics-card");

        btnToggle.addEventListener("click", () => {
            const collapsed = box.classList.toggle("collapsed");

            if (card) {
                card.classList.toggle("expanded", !collapsed);
            }

            btnToggle.textContent = collapsed ? "More" : "Less";
        });
    }

    // --- Track Info Drawer Events ---
    const btnTrackInfo = document.getElementById("btn-track-info");
    const btnTrackInfoClose = document.getElementById("btn-track-info-close");
    const infoBackdrop = document.getElementById("info-backdrop");

    if (btnTrackInfo) {
        btnTrackInfo.addEventListener("click", showTrackInfo);
    }

    if (btnTrackInfoClose) {
        btnTrackInfoClose.addEventListener("click", closeTrackInfoDrawer);
    }

    if (infoBackdrop) {
        infoBackdrop.addEventListener("click", closeTrackInfoDrawer);
    }
});

document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        clearInterval(statusInterval);
        clearInterval(recInterval);
        statusInterval = null;
        recInterval = null;
        console.log("Dashboard paused (tab hidden)");
    } else {
        statusInterval = setInterval(loadStatus, 15000);
        recInterval = setInterval(loadRecognizerStatus, 15000);

        loadStatus();
        loadRecognizerStatus();

        console.log("Dashboard resumed (tab visible)");
    }
});
