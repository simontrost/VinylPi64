/* Music library search and source-scoped removal of incorrect play history. */
document.addEventListener("DOMContentLoaded", () => {
    const input = document.getElementById("stats-search-input");
    const results = document.getElementById("stats-search-results");
    const feedback = document.getElementById("stats-search-feedback");
    const more = document.getElementById("stats-search-more");
    const pageStatus = document.getElementById("stats-search-page-status");
    const yearPicker = document.getElementById("stats-year-select");
    const backLink = document.getElementById("library-back");
    if (!input || !results || !feedback || !more || !pageStatus || !yearPicker) return;

    const PAGE_SIZE = 30;
    const kinds = ["artist", "album", "song"];
    const names = { artist: "Artists", album: "Albums", song: "Songs" };
    const icons = {
        artist: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.2 3-7 8-7s8 2.8 8 7"/>',
        album: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2"/><path d="M12 3a9 9 0 0 1 9 9"/>',
        song: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    };
    const query = new URLSearchParams(window.location.search);
    let kind = kinds.includes(query.get("type")) ? query.get("type") : "all";
    let scope = ["vinyl", "spotify", "combined"].includes(query.get("scope")) ? query.get("scope") : "vinyl";
    let year = /^(19|20)\d{2}$/.test(query.get("year") || "") ? query.get("year") : "all";
    let loaded = 0;
    let total = 0;
    let requestId = 0;
    let controller = null;
    let debounce = null;
    const groups = new Map();
    const confirmDialog = document.getElementById("library-delete-dialog");
    const deleteTitle = document.getElementById("library-delete-title");
    const deleteDetails = document.getElementById("library-delete-details");
    const deleteCancel = document.getElementById("library-delete-cancel");
    const deleteSubmit = document.getElementById("library-delete-submit");
    let pendingDelete = null;
    let deleting = false;

    input.value = (query.get("q") || "").slice(0, 120);

    function updateLocation() {
        const params = new URLSearchParams({ scope, year });
        if (kind !== "all") params.set("type", kind);
        if (input.value.trim()) params.set("q", input.value.trim());
        window.history.replaceState(null, "", `${window.location.pathname}?${params}`);
        if (backLink) backLink.href = `/stats.html?${new URLSearchParams({ scope, year })}`;
    }

    function syncControls() {
        document.querySelectorAll("[data-search-type]").forEach(button => {
            const active = button.dataset.searchType === kind;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-pressed", String(active));
        });
        document.querySelectorAll("[data-stats-scope]").forEach(button => {
            const active = button.dataset.statsScope === scope;
            button.classList.toggle("active", active);
            button.setAttribute("aria-pressed", String(active));
        });
        yearPicker.value = year;
    }

    function clearResults(message) {
        groups.clear();
        results.replaceChildren();
        loaded = 0;
        total = 0;
        more.classList.add("hidden");
        more.disabled = false;
        pageStatus.textContent = "";
        feedback.textContent = message;
    }

    function svgIcon(type) {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 24 24");
        svg.setAttribute("aria-hidden", "true");
        svg.innerHTML = icons[type]; // Constant SVG markup, never server-supplied HTML.
        return svg;
    }

    function sectionFor(type) {
        if (groups.has(type)) return groups.get(type);
        const section = document.createElement("section");
        section.className = `card library-group library-group--${type}`;
        const header = document.createElement("header");
        header.className = "library-group-header";
        const icon = document.createElement("span");
        icon.className = "library-group-icon";
        icon.append(svgIcon(type));
        const title = document.createElement("h2");
        title.textContent = names[type];
        const meta = document.createElement("span");
        meta.textContent = "0 shown";
        header.append(icon, title, meta);
        const list = document.createElement("ul");
        list.className = "library-group-list";
        section.append(header, list);
        // Keep categories in a predictable order even when more results arrive.
        const next = kinds.slice(kinds.indexOf(type) + 1).map(t => groups.get(t)?.section).find(Boolean);
        results.insertBefore(section, next || null);
        const entry = { section, list, meta, count: 0 };
        groups.set(type, entry);
        return entry;
    }

    function artworkFor(hit) {
        const artwork = document.createElement("span");
        artwork.className = "library-artwork";
        if (hit.kind === "album" || hit.kind === "song") {
            try {
                const url = new URL(hit.cover_url);
                if (["https:", "http:"].includes(url.protocol)) {
                    const img = document.createElement("img");
                    img.src = url.href;
                    img.alt = "";
                    img.loading = "lazy";
                    artwork.append(img);
                }
            } catch (_) { /* No usable artwork; use the category icon. */ }
        }
        if (!artwork.childNodes.length) {
            if (hit.kind === "artist" && hit.title) {
                artwork.textContent = hit.title.trim().charAt(0).toUpperCase();
            } else {
                artwork.append(svgIcon(hit.kind));
            }
        }
        return artwork;
    }

    function openDeleteDialog(hit) {
        if (deleting || !confirmDialog || !Array.isArray(hit.delete_entries) || !hit.delete_entries.length) return;
        pendingDelete = hit;
        deleteTitle.textContent = `Delete “${hit.title}”?`;
        const sources = [...new Set(hit.delete_entries.map(entry => entry.source))];
        const sourceLabel = sources.map(value => value === "spotify" ? "Spotify" : "Vinyl").join(" + ");
        deleteDetails.textContent = `Remove all recorded plays of this song from ${sourceLabel}, including artist and yearly song statistics. This cannot be undone. Your Discogs collection will not be changed.`;
        confirmDialog.showModal();
    }

    async function deletePendingSong() {
        if (!pendingDelete || deleting) return;
        deleting = true;
        deleteSubmit.disabled = true;
        deleteCancel.disabled = true;
        deleteSubmit.textContent = "Deleting…";
        try {
            const response = await fetch("/api/stats/song/delete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ entries: pendingDelete.delete_entries }),
                cache: "no-store",
            });
            const body = await response.json();
            if (!response.ok || !body.ok) throw new Error(body.error || `HTTP ${response.status}`);
            confirmDialog.close();
            pendingDelete = null;
            startSearch();
            feedback.textContent = `${body.removed_plays} play${body.removed_plays === 1 ? "" : "s"} deleted. Discogs entries remain in your collection.`;
        } catch (error) {
            console.error("Could not delete song history:", error);
            deleteDetails.textContent = `Could not delete this song: ${error.message}. No changes were saved.`;
        } finally {
            deleting = false;
            deleteSubmit.disabled = false;
            deleteCancel.disabled = false;
            deleteSubmit.textContent = "Delete song";
        }
    }

    function attachSwipe(item, surface) {
        let startX = null;
        let startY = null;
        let dragging = false;
        const reveal = () => item.classList.toggle("is-revealed", true);
        const close = () => item.classList.remove("is-revealed");
        surface.addEventListener("touchstart", event => {
            if (event.touches.length !== 1) return;
            startX = event.touches[0].clientX;
            startY = event.touches[0].clientY;
            dragging = false;
        }, { passive: true });
        surface.addEventListener("touchmove", event => {
            if (startX === null || event.touches.length !== 1) return;
            const dx = event.touches[0].clientX - startX;
            const dy = event.touches[0].clientY - startY;
            if (Math.abs(dy) > Math.abs(dx)) { startX = null; return; }
            if (Math.abs(dx) > 14) dragging = true;
        }, { passive: true });
        surface.addEventListener("touchend", event => {
            if (startX === null || !dragging) return;
            const dx = event.changedTouches[0].clientX - startX;
            if (dx < -45) reveal();
            else if (dx > 45) close();
            startX = null;
        }, { passive: true });
        surface.addEventListener("touchcancel", () => { startX = null; }, { passive: true });
    }

    function createHit(hit, albumUnit) {
        const item = document.createElement("li");
        item.className = "library-swipe-item";
        const surface = document.createElement("div");
        surface.className = "library-hit";
        surface.append(artworkFor(hit));

        const copy = document.createElement("div");
        copy.className = "library-hit-copy";
        const type = document.createElement("span");
        type.className = "library-hit-kind";
        type.textContent = hit.kind;
        const title = document.createElement("strong");
        title.textContent = hit.title;
        copy.append(type, title);
        const description = hit.kind === "song"
            ? [hit.artist, hit.album].filter(Boolean).join(" · ")
            : hit.kind === "album" ? hit.artist : "";
        if (description) {
            const details = document.createElement("span");
            details.className = "library-hit-details";
            details.textContent = description;
            copy.append(details);
        }
        if (hit.in_collection) {
            const collection = document.createElement("span");
            collection.className = "library-collection";
            collection.textContent = "In your collection";
            copy.append(collection);
        }
        surface.append(copy);

        const count = document.createElement("div");
        count.className = "library-hit-count";
        if (hit.count === 0) count.classList.add("is-zero");
        const number = document.createElement("strong");
        number.textContent = Number(hit.count).toLocaleString();
        const label = document.createElement("span");
        const unit = hit.kind === "album" ? albumUnit : "play";
        label.textContent = Number(hit.count) === 1 ? unit : `${unit}s`;
        count.append(number, label);
        surface.append(count);
        if (hit.kind === "song" && Array.isArray(hit.delete_entries) && hit.delete_entries.length) {
            item.classList.add("library-swipe-item--editable");
            const action = document.createElement("button");
            action.type = "button";
            action.className = "library-delete-action";
            action.textContent = "Delete";
            action.setAttribute("aria-label", `Delete history for ${hit.title} by ${hit.artist}`);
            action.addEventListener("click", () => openDeleteDialog(hit));
            item.append(action);
            const trigger = document.createElement("button");
            trigger.type = "button";
            trigger.className = "library-delete-trigger";
            trigger.setAttribute("aria-label", `Delete history for ${hit.title} by ${hit.artist}`);
            trigger.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>';
            trigger.addEventListener("click", () => openDeleteDialog(hit));
            surface.append(trigger);
            attachSwipe(item, surface);
        }
        item.append(surface);
        return item;
    }

    async function fetchPage(id, append) {
        if (id !== requestId || controller) return;
        const q = input.value.trim();
        if (q.length < 2) return;
        const offset = append ? loaded : 0;
        controller = new AbortController();
        more.disabled = true;
        if (append) {
            more.textContent = "Loading…";
            pageStatus.textContent = "Loading more results…";
        }
        const params = new URLSearchParams({ q, type: kind, scope, year, offset: String(offset), limit: String(PAGE_SIZE) });
        try {
            const response = await fetch(`/api/stats/search?${params}`, { cache: "no-store", signal: controller.signal });
            if (!response.ok) throw new Error(`Search failed (${response.status})`);
            const data = await response.json();
            if (id !== requestId) return;
            if (!Array.isArray(data.items)) throw new Error("Invalid search response");
            total = Math.max(0, Number(data.total) || 0);
            let firstAdded = null;
            for (const hit of data.items) {
                if (!kinds.includes(hit.kind)) continue;
                const row = createHit(hit, data.album_count_unit || "session");
                const group = sectionFor(hit.kind);
                group.list.append(row);
                group.count++;
                group.meta.textContent = `${group.count} shown`;
                if (!firstAdded) firstAdded = row;
            }
            // The backend paginates the whole result set, including mixed types.
            loaded += data.items.length;
            const sourceLabel = scope === "spotify" ? "Spotify" : scope === "combined" ? "Vinyl + Spotify" : "Vinyl + Discogs";
            feedback.textContent = total
                ? `${total.toLocaleString()} result${total === 1 ? "" : "s"} · ${sourceLabel}${year === "all" ? "" : ` · ${year}`}`
                : "No matches in your listening history or collection.";
            pageStatus.textContent = total ? `Showing ${Math.min(loaded, total).toLocaleString()} of ${total.toLocaleString()} results` : "";
            const hasMore = loaded < total && data.items.length > 0;
            more.classList.toggle("hidden", !hasMore);
            if (hasMore) more.textContent = `Show more results`;
            if (loaded < total && !data.items.length) pageStatus.textContent = "No further results were returned.";
            // New items are inserted above the pagination button: bring the first
            // new row into view instead of leaving the user at the page bottom.
            if (append && firstAdded) {
                requestAnimationFrame(() => firstAdded.scrollIntoView({ behavior: "auto", block: "center" }));
            }
        } catch (error) {
            if (id !== requestId || error.name === "AbortError") return;
            console.error("Library search failed:", error);
            const message = append ? "Could not load more results. Try again." : "Search is currently unavailable. Please try again.";
            if (append) pageStatus.textContent = message;
            else feedback.textContent = message;
            more.classList.toggle("hidden", !append);
        } finally {
            if (id === requestId) {
                controller = null;
                more.disabled = false;
                if (!more.classList.contains("hidden")) more.textContent = "Show more results";
            }
        }
    }

    function startSearch(delay = 0) {
        const id = ++requestId;
        clearTimeout(debounce);
        controller?.abort();
        controller = null;
        updateLocation();
        const q = input.value.trim();
        clearResults(q.length < 2 ? "Enter at least 2 characters to search." : "Searching…");
        if (q.length >= 2) debounce = setTimeout(() => fetchPage(id, false), delay);
    }

    if (confirmDialog) {
        deleteCancel?.addEventListener("click", () => confirmDialog.close());
        deleteSubmit?.addEventListener("click", deletePendingSong);
        confirmDialog.addEventListener("close", () => {
            if (!deleting) pendingDelete = null;
        });
    }
    input.addEventListener("input", () => startSearch(280));
    more.addEventListener("click", () => fetchPage(requestId, true));
    document.querySelectorAll("[data-search-type]").forEach(button => button.addEventListener("click", () => {
        if (kind === button.dataset.searchType) return;
        kind = button.dataset.searchType;
        syncControls();
        startSearch();
    }));
    document.querySelectorAll("[data-stats-scope]").forEach(button => button.addEventListener("click", () => {
        if (scope === button.dataset.statsScope) return;
        scope = button.dataset.statsScope;
        syncControls();
        startSearch();
    }));
    yearPicker.addEventListener("change", () => {
        year = yearPicker.value || "all";
        startSearch();
    });

    fetch("/api/stats/years", { cache: "no-store" })
        .then(response => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
        .then(data => {
            yearPicker.replaceChildren(new Option("All time", "all"));
            for (const y of data.years || []) yearPicker.add(new Option(String(y), String(y)));
            if (year !== "all" && ![...yearPicker.options].some(option => option.value === year)) {
                yearPicker.add(new Option(year, year));
            }
            yearPicker.value = year;
        })
        .catch(error => console.warn("Could not load statistics years:", error));

    syncControls();
    startSearch();
});
