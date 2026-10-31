/* Search recorded playback and locally cached Discogs releases/tracks. */
document.addEventListener("DOMContentLoaded", () => {
    const input = document.getElementById("stats-search-input");
    const results = document.getElementById("stats-search-results");
    const feedback = document.getElementById("stats-search-feedback");
    const more = document.getElementById("stats-search-more");
    if (!input || !results || !feedback || !more) return;

    const PAGE_SIZE = 30;
    let kind = "all";
    let loaded = 0;
    let requestId = 0;
    let controller;
    let debounce;

    function reset(message) {
        results.replaceChildren();
        loaded = 0;
        more.classList.add("hidden");
        feedback.textContent = message;
    }

    function imageFor(hit) {
        const frame = document.createElement("span");
        frame.className = "stats-search-cover";
        if (hit.cover_url) {
            try {
                const url = new URL(hit.cover_url);
                if (url.protocol === "https:" || url.protocol === "http:") {
                    const img = document.createElement("img");
                    img.src = url.href;
                    img.alt = "";
                    img.loading = "lazy";
                    frame.appendChild(img);
                }
            } catch (_) { /* Keep the empty artwork placeholder. */ }
        }
        if (!frame.childNodes.length) {
            frame.textContent = hit.kind === "artist" ? "♪" : "♫";
        }
        return frame;
    }

    function renderHit(hit, unit) {
        const item = document.createElement("li");
        item.className = "stats-search-result";
        item.appendChild(imageFor(hit));

        const copy = document.createElement("div");
        copy.className = "stats-search-result-copy";
        const name = document.createElement("strong");
        name.textContent = hit.title;
        const details = document.createElement("span");
        const type = hit.kind === "song" ? "Song" : hit.kind === "album" ? "Album" : "Artist";
        const secondary = hit.kind === "song"
            ? [hit.artist, hit.album].filter(Boolean).join(" · ")
            : (hit.kind === "album" ? hit.artist : "");
        details.textContent = [type, secondary].filter(Boolean).join(" · ");
        copy.append(name, details);
        if (hit.in_collection) {
            const collection = document.createElement("span");
            collection.className = "stats-search-collection";
            collection.textContent = "In your collection";
            copy.appendChild(collection);
        }
        item.appendChild(copy);

        const plays = document.createElement("div");
        plays.className = "stats-search-count";
        if (hit.count === 0) plays.classList.add("is-zero");
        const value = document.createElement("strong");
        value.textContent = Number(hit.count).toLocaleString();
        const label = document.createElement("span");
        const singular = hit.kind === "album" ? unit : "play";
        label.textContent = Number(hit.count) === 1 ? singular : `${singular}s`;
        plays.append(value, label);
        item.appendChild(plays);
        return item;
    }

    async function search(append = false) {
        const q = input.value.trim();
        controller?.abort();
        const id = ++requestId;
        if (q.length < 2) {
            reset("Enter at least 2 characters to search.");
            return;
        }
        if (!append) reset("Searching…");
        else more.disabled = true;
        controller = new AbortController();
        const params = new URLSearchParams({
            q, type: kind, scope: vinylPiStatsScope, year: vinylPiStatsYear,
            offset: String(append ? loaded : 0), limit: String(PAGE_SIZE),
        });
        try {
            const response = await fetch(`/api/stats/search?${params}`, {
                cache: "no-store", signal: controller.signal,
            });
            if (!response.ok) throw new Error(`Search failed (${response.status})`);
            const data = await response.json();
            if (id !== requestId) return;
            for (const hit of data.items || []) {
                results.appendChild(renderHit(hit, data.album_count_unit || "session"));
            }
            loaded += (data.items || []).length;
            const total = Number(data.total) || 0;
            feedback.textContent = total
                ? `${total.toLocaleString()} result${total === 1 ? "" : "s"} · ${vinylPiStatsScope === "spotify" ? "Spotify" : vinylPiStatsScope === "combined" ? "Vinyl + Spotify" : "Vinyl + Discogs"}${vinylPiStatsYear === "all" ? "" : ` · ${vinylPiStatsYear}`}`
                : "No matches in your listening history or collection.";
            more.classList.toggle("hidden", loaded >= total);
        } catch (error) {
            if (error.name === "AbortError" || id !== requestId) return;
            feedback.textContent = "Search is currently unavailable. Please try again.";
            console.error(error);
            if (!append) results.replaceChildren();
        } finally {
            if (id === requestId) more.disabled = false;
        }
    }

    function scheduleSearch() {
        clearTimeout(debounce);
        controller?.abort();
        debounce = setTimeout(() => search(), 320);
    }
    input.addEventListener("input", scheduleSearch);
    more.addEventListener("click", () => search(true));
    document.querySelectorAll("[data-search-type]").forEach((button) => {
        button.addEventListener("click", () => {
            kind = button.dataset.searchType;
            document.querySelectorAll("[data-search-type]").forEach((candidate) => {
                const active = candidate === button;
                candidate.classList.toggle("is-active", active);
                candidate.setAttribute("aria-pressed", String(active));
            });
            clearTimeout(debounce);
            search();
        });
    });
    document.querySelectorAll("[data-stats-scope]").forEach((button) => {
        button.addEventListener("click", () => search());
    });
    document.getElementById("stats-year-select")?.addEventListener("change", () => search());
});
