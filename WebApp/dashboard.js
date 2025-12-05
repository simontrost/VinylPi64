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

loadStatus();
setInterval(loadStatus, 5000);
