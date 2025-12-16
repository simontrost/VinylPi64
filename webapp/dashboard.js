let CURRENT_TRACK = { artist: "", title: "" };

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
            return;
        }

        const title = st.title || "Unknown title";
        const artist = st.artist || "Unknown artist";
        const album = st.album || "";

        artistEl.innerText = artist;
        titleEl.innerText = title;
        albumEl.innerText = album ? `${album}` : "";

        coverEl.src = st.cover_url || "/logo.png";

        CURRENT_TRACK.artist = artist;
        CURRENT_TRACK.title = title;

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
                const lr = await fetch(`/api/lyrics?artist=${encodeURIComponent(artist)}&title=${encodeURIComponent(title)}`);
                const res = await lr.json();

                if (!res.ok || !res.lyrics) {
                    box.textContent = "No lyrics found. Opening Genius...";
                    window.open(`https://genius.com/search?q=${encodeURIComponent(artist + " " + title)}`, "_blank", "noopener,noreferrer");
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

            if (card) card.classList.toggle("expanded", !collapsed);

            btnToggle.textContent = collapsed ? "More" : "Less";
        });

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
