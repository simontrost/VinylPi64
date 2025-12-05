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

        if (st.cover_url) {
            coverEl.src = st.cover_url;
        } else {
            coverEl.src = "/logo.png";
        }

    } catch (e) {
        document.getElementById("song-title").innerText = "Fehler beim Laden";
    }
}

async function loadRecognizerStatus() {
    const statusEl = document.getElementById("rec-status");
    const btnStart = document.getElementById("btn-start-rec");
    const btnStop = document.getElementById("btn-stop-rec");

    if (!statusEl || !btnStart || !btnStop) return;

    try {
        const r = await fetch("/api/recognizer/status");
        const data = await r.json();

        if (data.running) {
            statusEl.textContent = "Läuft";
            statusEl.classList.add("status-running");
            statusEl.classList.remove("status-stopped");
            btnStart.disabled = true;
            btnStop.disabled = false;
        } else {
            statusEl.textContent = "Gestoppt";
            statusEl.classList.add("status-stopped");
            statusEl.classList.remove("status-running");
            btnStart.disabled = false;
            btnStop.disabled = true;
        }
    } catch (e) {
        console.error(e);
        statusEl.textContent = "Statusfehler";
        btnStart.disabled = false;
        btnStop.disabled = false;
    }
}

async function startRecognizer() {
    await fetch("/api/recognizer/start", { method: "POST" });
    await loadRecognizerStatus();
}

async function stopRecognizer() {
    await fetch("/api/recognizer/stop", { method: "POST" });
    await loadRecognizerStatus();
}

document.getElementById("btn-start-rec")?.addEventListener("click", startRecognizer);
document.getElementById("btn-stop-rec")?.addEventListener("click", stopRecognizer);

loadStatus();
setInterval(loadStatus, 5000);

loadRecognizerStatus();
setInterval(loadRecognizerStatus, 5000);

