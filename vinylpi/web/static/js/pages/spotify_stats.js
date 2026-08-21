/* Vinyl / Spotify / Combined statistics selector. Loaded after stats.js. */

let vinylPiStatsScope = "vinyl";

function statsScopeCopy(scope) {
    return {
        vinyl: {
            label: "Vinyl listening overview",
            description: "Calculated from confirmed vinyl recognitions.",
        },
        spotify: {
            label: "Spotify listening overview",
            description: "Calculated from Spotify playback progress while the Spotify source is enabled.",
        },
        combined: {
            label: "Combined listening overview",
            description: "Vinyl and Spotify listening data combined.",
        },
    }[scope] || {};
}

function updateStatsScopeUI() {
    document.querySelectorAll("[data-stats-scope]").forEach((button) => {
        const active = button.dataset.statsScope === vinylPiStatsScope;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
    });

    const copy = statsScopeCopy(vinylPiStatsScope);
    const overview = document.getElementById("stats-overview-label");
    const description = document.getElementById("stats-description");
    if (overview) overview.textContent = copy.label || "Listening overview";
    if (description) description.textContent = copy.description || "";

    const sharePanel = document.getElementById("stats-share-panel");
    if (sharePanel) sharePanel.classList.toggle("hidden", vinylPiStatsScope !== "vinyl");
}

renderStats = function renderScopedStats(data = {}) {
    const minutes = Number(data.total_minutes_listened) || 0;
    const minutesElement = document.getElementById("stats-minutes");
    if (minutesElement) minutesElement.textContent = Math.round(minutes).toLocaleString();

    const songs = Array.isArray(data.top_songs) ? data.top_songs : [];
    const artists = Array.isArray(data.top_artists) ? data.top_artists : [];
    const albums = Array.isArray(data.top_albums) ? data.top_albums : [];
    const albumUnit = String(data.album_count_unit || (vinylPiStatsScope === "vinyl" ? "session" : "play"));

    const songsList = document.getElementById("stats-songs");
    const artistsList = document.getElementById("stats-artists");
    const albumsList = document.getElementById("stats-albums");

    if (songsList) {
        setupExpandableList(
            songsList,
            songs,
            (song, index) => createRankedItem(
                index + 1,
                song.title,
                song.artist,
                formatCount(song.count, "play"),
                song.genre || "",
            ),
            vinylPiStatsScope === "spotify" ? "No Spotify songs tracked yet." : "No songs recorded yet.",
        );
    }

    if (artistsList) {
        setupExpandableList(
            artistsList,
            artists,
            (artist, index) => createRankedItem(index + 1, artist.name, "", formatCount(artist.count, "play")),
            "No artists recorded yet.",
        );
    }

    if (albumsList) {
        setupExpandableList(
            albumsList,
            albums,
            (album, index) => createRankedItem(
                index + 1,
                album.name,
                album.artist || "",
                formatCount(album.count, albumUnit),
            ),
            "No albums recorded yet.",
        );
    }

    const genreEmpty = document.getElementById("genre-empty");
    if (genreEmpty) {
        genreEmpty.textContent = vinylPiStatsScope === "spotify"
            ? "No genre data available yet. Spotify genres are supplemented with Last.fm tags when needed."
            : (vinylPiStatsScope === "combined"
                ? "No genre data available yet."
                : "Genre statistics will appear after songs are recognized again.");
    }

    renderGenreChart(data.radar_genres || data.top_genres || []);
    renderAlbumCarousel(data.top_album_covers || []);
};

loadStats = async function loadScopedStats() {
    updateStatsScopeUI();
    try {
        const response = await fetch(`/api/stats?scope=${encodeURIComponent(vinylPiStatsScope)}`, {
            cache: "no-store",
        });
        if (!response.ok) throw new Error(`Statistics request failed: ${response.status}`);
        renderStats(await response.json());
    } catch (error) {
        console.error(error);
        renderStats({});
    }
};

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-stats-scope]").forEach((button) => {
        button.addEventListener("click", () => {
            vinylPiStatsScope = button.dataset.statsScope || "vinyl";
            loadStats();
        });
    });
    updateStatsScopeUI();
});
