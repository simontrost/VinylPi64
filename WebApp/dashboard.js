async function loadStatus() {
    try {
        const r = await fetch("/api/status");
        const st = await r.json();

        const titleEl = document.getElementById("song-title");
        const artistEl = document.getElementById("song-artist");
        const albumEl = document.getElementById("song-album");
        const coverEl = document.getElementById("song-cover");

        if (st.error) {
            titleEl.innerText = "Keine Daten";
            artistEl.innerText = "";
            albumEl.innerText = "";
            coverEl.src = "/logo.png";
            return;
        }

        const title = st.title || "Unbekannter Titel";
        const artist = st.artist || "Unbekannter Artist";
        const album = st.album || "";

        artistEl.innerText = artist;
        titleEl.innerText = title;
        albumEl.innerText = album ? `Album: ${album}` : "";

        coverEl.src = st.cover_url || "/logo.png";

    } catch (e) {
        console.error(e);
        document.getElementById("song-title").innerText = "Fehler beim Laden";
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
            statusEl.textContent = "Läuft";
            statusEl.classList.add("rec-status-running");
        } else {
            statusEl.textContent = "Gestoppt";
            statusEl.classList.add("rec-status-stopped");
        }
    } catch (e) {
        console.error(e);
        statusEl.textContent = "Statusfehler";
        statusEl.classList.remove("rec-status-running", "rec-status-stopped");
    }
}

async function setRecognizerRunning(shouldRun) {
    const toggle = document.getElementById("recognizerToggle");
    const statusEl = document.getElementById("rec-status-text");
    if (!toggle || !statusEl) return;

    toggle.disabled = true;
    statusEl.textContent = "Ändere Status …";

    try {
        const url = shouldRun ? "/api/recognizer/start" : "/api/recognizer/stop";
        await fetch(url, { method: "POST" });
    } catch (e) {
        console.error(e);
    }

    await loadRecognizerStatus();
    toggle.disabled = false;
}

document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.getElementById("recognizerToggle");
    if (toggle) {
        toggle.addEventListener("change", (e) => {
            setRecognizerRunning(e.target.checked);
        });
    }

    const btnStart = document.getElementById("btn-start-rec");
    if (btnStart) {
        btnStart.addEventListener("click", () => setRecognizerRunning(true));
    }

    const btnStop = document.getElementById("btn-stop-rec");
    if (btnStop) {
        btnStop.addEventListener("click", () => setRecognizerRunning(false));
    }

    loadStatus();
    loadRecognizerStatus();
    setInterval(loadStatus, 5000);
    setInterval(loadRecognizerStatus, 5000);
});
