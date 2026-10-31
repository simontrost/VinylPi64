/* Vinyl / Spotify / Combined statistics selector. Loaded after stats.js. */

let vinylPiStatsScope = "vinyl";
let vinylPiStatsYear = "all";
let vinylPiStatsRequestId = 0;
let vinylPiStatsController = null;
// Keep already rendered scopes in memory while this page is open. Values are
// always revalidated, but switching tabs no longer flashes an empty overview.
const vinylPiStatsCache = new Map();

function statsScopeCopy(scope) {
    return {
        vinyl: {
            label: "Vinyl listening overview",
        },
        spotify: {
            label: "Spotify listening overview",
        },
        combined: {
            label: "Combined listening overview",
        },
    }[scope] || {};
}

function updateStatsScopeUI() {
    const layout = document.querySelector(".stats-content-layout");
    if (layout) layout.dataset.statsScope = vinylPiStatsScope;
    document.querySelectorAll("[data-stats-scope]").forEach((button) => {
        const active = button.dataset.statsScope === vinylPiStatsScope;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
    });

    const libraryLink = document.getElementById("stats-library-link");
    if (libraryLink) {
        const params = new URLSearchParams({ scope: vinylPiStatsScope, year: vinylPiStatsYear });
        libraryLink.href = `/library.html?${params}`;
    }

    const copy = statsScopeCopy(vinylPiStatsScope);
    const overview = document.getElementById("stats-overview-label");
    if (overview) overview.textContent = copy.label || "Listening overview";

    const shareDescription = document.getElementById("stats-share-description");
    if (shareDescription) {
        shareDescription.textContent = "Share your VinylPi listening statistics with friends.";
    }

    const pickupUsageRow = document.getElementById("stats-pickup-usage-row");
    if (pickupUsageRow) pickupUsageRow.classList.toggle("hidden", vinylPiStatsScope !== "vinyl");
}

function renderStats(data = {}) {
    const minutes = Number(data.total_minutes_listened) || 0;
    const minutesElement = document.getElementById("stats-minutes");
    if (minutesElement) minutesElement.textContent = Math.round(minutes).toLocaleString();
    const pickupUsage = document.getElementById("stats-pickup-usage");
    if (pickupUsage) pickupUsage.textContent = formatPickupDuration(data.pickup_usage_seconds);

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

async function loadStats() {
    const scope = vinylPiStatsScope;
    const year = vinylPiStatsYear;
    const requestId = ++vinylPiStatsRequestId;
    vinylPiStatsController?.abort();
    const controller = new AbortController();
    vinylPiStatsController = controller;
    // Never display another tab's statistics under the newly selected tab.
    updateStatsScopeUI();
    const cacheKey = `${scope}:${year}`;
    const cached = vinylPiStatsCache.get(cacheKey);
    renderStats(cached || {});
    try {
        const response = await fetch(`/api/stats?scope=${encodeURIComponent(scope)}&year=${encodeURIComponent(year)}`, {
            cache: "no-store", signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Statistics request failed: ${response.status}`);
        const data = await response.json();
        if (requestId !== vinylPiStatsRequestId || scope !== vinylPiStatsScope || year !== vinylPiStatsYear) return;
        vinylPiStatsCache.set(cacheKey, data);
        // Chart.js and the album carousel are expensive on a Pi Zero. Avoid
        // rebuilding them when a background revalidation changed nothing.
        if (!cached || JSON.stringify(cached) !== JSON.stringify(data)) {
            renderStats(data);
        }
    } catch (error) {
        if (error.name === "AbortError" || requestId !== vinylPiStatsRequestId) return;
        console.error(error);
        if (!cached) renderStats({});
    } finally {
        if (vinylPiStatsController === controller) vinylPiStatsController = null;
    }
};

document.addEventListener("DOMContentLoaded", () => {
    // Preserve the library page's source/period when returning to Statistics.
    const fromLibrary = new URLSearchParams(window.location.search);
    const initialScope = fromLibrary.get("scope");
    const initialYear = fromLibrary.get("year");
    if (["vinyl", "spotify", "combined"].includes(initialScope)) vinylPiStatsScope = initialScope;
    if (initialYear === "all" || /^\d{4}$/.test(initialYear || "")) {
        vinylPiStatsYear = initialYear;
        const yearPicker = document.getElementById("stats-year-select");
        if (yearPicker) yearPicker.value = vinylPiStatsYear;
    }
    document.querySelectorAll("[data-stats-scope]").forEach((button) => {
        button.addEventListener("click", () => {
            vinylPiStatsScope = button.dataset.statsScope || "vinyl";
            loadStats();
        });
    });
    const yearPicker = document.getElementById('stats-year-select');
    if (yearPicker) {
        yearPicker.addEventListener('change', () => {
            vinylPiStatsYear = yearPicker.value || 'all';
            loadStats();
        });
        fetch('/api/stats/years', {cache: 'no-store'})
            .then(response => response.ok ? response.json() : Promise.reject(response.status))
            .then(data => {
                const selected = vinylPiStatsYear;
                yearPicker.replaceChildren(new Option('All time', 'all'));
                (data.years || []).forEach(year => yearPicker.add(new Option(String(year), String(year))));
                yearPicker.value = selected;
            })
            .catch(error => console.warn('Could not load available statistics years:', error));
    }
    updateStatsScopeUI();
});
