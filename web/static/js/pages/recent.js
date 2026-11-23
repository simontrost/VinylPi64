/* Source-filtered timeline of genuine, timestamped playback events. */
document.addEventListener("DOMContentLoaded", () => {
    const results = document.getElementById("recent-results");
    const status = document.getElementById("recent-status");
    const more = document.getElementById("recent-more");
    const back = document.getElementById("recent-back");
    if (!results || !status || !more) return;

    const validScopes = ["vinyl", "spotify", "combined"];
    const query = new URLSearchParams(location.search);
    let scope = validScopes.includes(query.get("scope")) ? query.get("scope") : "vinyl";
    let offset = 0;
    let controller = null;
    let requestId = 0;
    const pageSize = 40;
    const groups = new Map();
    const dayFormatter = new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    const timeFormatter = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });

    function syncScope() {
        document.querySelectorAll("[data-recent-scope]").forEach(button => {
            const active = scope === button.dataset.recentScope;
            button.classList.toggle("active", active);
            button.setAttribute("aria-pressed", String(active));
        });
        back.href = `/stats.html?scope=${encodeURIComponent(scope)}`;
        history.replaceState(null, "", `/recent.html?scope=${encodeURIComponent(scope)}`);
    }

    function section(date) {
        const day = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
        if (groups.has(day)) return groups.get(day);
        const wrapper = document.createElement("section");
        wrapper.className = "card recent-day";
        const heading = document.createElement("h2");
        heading.className = "recent-day-heading";
        heading.textContent = dayFormatter.format(date);
        const count = document.createElement("span");
        count.className = "recent-day-count";
        count.textContent = "";
        heading.append(count);
        const list = document.createElement("ul");
        list.className = "recent-list";
        wrapper.append(heading, list);
        results.append(wrapper);
        const group = { list, count, total: 0 };
        groups.set(day, group);
        return group;
    }

    function rowFor(item, date) {
        const row = document.createElement("li");
        row.className = "recent-item";
        const cover = document.createElement("span");
        cover.className = "recent-cover";
        try {
            const url = new URL(item.cover_url);
            if (["https:", "http:"].includes(url.protocol)) {
                const image = document.createElement("img");
                image.src = url.href;
                image.alt = "";
                image.loading = "lazy";
                cover.append(image);
            }
        } catch (_) { /* No cover is available. */ }
        if (!cover.childNodes.length) cover.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>';
        const copy = document.createElement("div");
        copy.className = "recent-copy";
        const title = document.createElement("strong");
        title.className = "recent-title";
        title.textContent = item.title || "Unknown title";
        const subtitle = document.createElement("span");
        subtitle.className = "recent-subtitle";
        subtitle.textContent = [item.artist, item.album].filter(Boolean).join(" · ") || "Unknown artist";
        copy.append(title, subtitle);
        const meta = document.createElement("div");
        meta.className = "recent-meta";
        const time = document.createElement("time");
        time.className = "recent-time";
        time.dateTime = date.toISOString();
        time.textContent = timeFormatter.format(date);
        const source = document.createElement("span");
        source.className = `recent-source recent-source--${item.source === "spotify" ? "spotify" : "vinyl"}`;
        source.textContent = item.source === "spotify" ? "Spotify" : "Vinyl";
        meta.append(time, source);
        row.append(cover, copy, meta);
        return row;
    }

    async function loadMore() {
        if (controller) return;
        const id = requestId;
        controller = new AbortController();
        more.disabled = true;
        more.textContent = "Loading…";
        try {
            const params = new URLSearchParams({ scope, offset: String(offset), limit: String(pageSize) });
            const response = await fetch(`/api/stats/recent?${params}`, { cache: "no-store", signal: controller.signal });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (!Array.isArray(data.items)) throw new Error("Invalid history response");
            if (id !== requestId) return;
            for (const item of data.items) {
                const date = new Date(Number(item.occurred_at) * 1000);
                if (Number.isNaN(date.getTime())) continue;
                const group = section(date);
                group.list.append(rowFor(item, date));
                group.total += 1;
                group.count.textContent = `${group.total} song${group.total === 1 ? "" : "s"}`;
            }
            offset += data.items.length;
            status.textContent = offset ? `${offset} playback${offset === 1 ? "" : "s"} shown` : "No timestamped songs found for this source yet.";
            more.classList.toggle("hidden", !data.has_more);
        } catch (error) {
            if (id !== requestId || error.name === "AbortError") return;
            console.error("Recently played loading failed:", error);
            status.textContent = "Couldn't load playback history. Please try again.";
            more.classList.remove("hidden");
        } finally {
            if (id === requestId) {
                controller = null;
                more.disabled = false;
                more.textContent = "Show older songs";
            }
        }
    }

    document.querySelectorAll("[data-recent-scope]").forEach(button => button.addEventListener("click", () => {
        if (scope === button.dataset.recentScope) return;
        scope = button.dataset.recentScope;
        requestId += 1;
        controller?.abort();
        controller = null;
        offset = 0;
        groups.clear();
        results.replaceChildren();
        more.classList.add("hidden");
        status.textContent = "Loading history…";
        syncScope();
        loadMore();
    }));
    more.addEventListener("click", loadMore);
    syncScope();
    loadMore();
});
