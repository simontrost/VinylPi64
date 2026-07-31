const MAX_VISIBLE = 5;
let radarChart = null;
let albumCarouselTimer = null;
let albumCarouselIndex = 0;

function formatCount(value, singular, plural = `${singular}s`) {
    const count = Number(value) || 0;
    return `${count} ${count === 1 ? singular : plural}`;
}

function createEmptyItem(message) {
    const item = document.createElement("li");
    item.className = "stats-empty";
    item.textContent = message;
    return item;
}

function createRankedItem(rank, title, subtitle, countText, metaText = "") {
    const item = document.createElement("li");
    item.className = "stats-item";

    const rankElement = document.createElement("span");
    rankElement.className = "stats-rank";
    rankElement.textContent = `#${rank}`;

    const text = document.createElement("div");
    text.className = "stats-text";

    const main = document.createElement("div");
    main.className = "stats-main";
    main.textContent = title || "Unknown";
    text.appendChild(main);

    const sub = document.createElement("div");
    sub.className = "stats-sub";
    sub.textContent = [subtitle, metaText].filter(Boolean).join(" · ") || "\u00a0";
    text.appendChild(sub);

    const badge = document.createElement("span");
    badge.className = "stats-badge";
    badge.textContent = countText;

    item.append(rankElement, text, badge);
    return item;
}

function setupExpandableList(listElement, items, renderItem, emptyMessage) {
    let expanded = false;

    const render = () => {
        listElement.replaceChildren();

        if (!items.length) {
            listElement.appendChild(createEmptyItem(emptyMessage));
            return;
        }

        const visibleItems = expanded ? items : items.slice(0, MAX_VISIBLE);
        visibleItems.forEach((item, index) => {
            listElement.appendChild(renderItem(item, index));
        });

        if (items.length > MAX_VISIBLE) {
            const wrapper = document.createElement("li");
            wrapper.className = "stats-toggle-wrapper";

            const button = document.createElement("button");
            button.type = "button";
            button.className = "stats-toggle";
            button.textContent = expanded ? "Show less" : `Show all ${items.length}`;
            button.addEventListener("click", () => {
                expanded = !expanded;
                render();
            });

            wrapper.appendChild(button);
            listElement.appendChild(wrapper);
        }
    };

    render();
}

function renderMetadataCoverage(coverage = {}) {
    const total = Number(coverage.songs_total) || 0;
    const withGenre = Number(coverage.songs_with_genre) || 0;
    const withShazamId = Number(coverage.songs_with_shazam_id) || 0;

    document.getElementById("metadata-genres").textContent = `${withGenre}/${total}`;
    document.getElementById("metadata-shazam-ids").textContent = `${withShazamId}/${total}`;

    const note = document.getElementById("metadata-note");
    if (note && total > 0 && (withGenre < total || withShazamId < total)) {
        note.textContent = "Older songs remain intact and receive metadata when recognized again.";
    }
}

function renderGenreChart(genres = []) {
    const canvas = document.getElementById("genre-radar");
    const empty = document.getElementById("genre-empty");
    if (!canvas || !empty) return;

    if (radarChart) {
        radarChart.destroy();
        radarChart = null;
    }

    if (!genres.length || typeof Chart === "undefined") {
        canvas.classList.add("hidden");
        empty.classList.remove("hidden");
        return;
    }

    canvas.classList.remove("hidden");
    empty.classList.add("hidden");

    const styles = getComputedStyle(document.documentElement);
    const textColor = styles.getPropertyValue("--text").trim() || "#f2f2f4";
    const gridColor = "rgba(255, 255, 255, 0.13)";

    radarChart = new Chart(canvas, {
        type: "radar",
        data: {
            labels: genres.map((genre) => genre.name),
            datasets: [{
                label: "Recognitions",
                data: genres.map((genre) => Number(genre.count) || 0),
                fill: true,
                backgroundColor: "rgba(124, 58, 237, 0.24)",
                borderColor: "rgba(239, 45, 143, 0.95)",
                pointBackgroundColor: "rgba(245, 197, 66, 1)",
                pointBorderColor: "rgba(245, 197, 66, 1)",
                borderWidth: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                r: {
                    beginAtZero: true,
                    ticks: { display: false, precision: 0 },
                    grid: { color: gridColor },
                    angleLines: { color: gridColor },
                    pointLabels: { color: textColor, font: { size: 11 } },
                },
            },
        },
    });
}

function renderAlbumCarousel(albums = []) {
    const root = document.getElementById("album-carousel");
    if (!root) return;

    if (albumCarouselTimer) {
        clearInterval(albumCarouselTimer);
        albumCarouselTimer = null;
    }

    root.replaceChildren();
    albumCarouselIndex = 0;
    const items = albums.filter((album) => album.cover_url).slice(0, 10);

    if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "stats-empty";
        empty.textContent = "No album covers available yet.";
        root.appendChild(empty);
        return;
    }

    items.forEach((album) => {
        const slide = document.createElement("div");
        slide.className = "album-slide";

        const image = document.createElement("img");
        image.src = album.cover_url;
        image.alt = `${album.name || "Album"} cover`;
        image.loading = "lazy";
        image.addEventListener("error", () => slide.remove(), { once: true });

        const title = document.createElement("div");
        title.className = "album-slide-title";
        title.textContent = `${album.name || "Unknown album"} · ${formatCount(album.count, "play")}`;

        slide.append(image, title);
        root.appendChild(slide);
    });

    updateAlbumCarousel();

    if (items.length > 1) {
        albumCarouselTimer = window.setInterval(() => {
            const slides = root.querySelectorAll(".album-slide");
            if (!slides.length) return;
            albumCarouselIndex = (albumCarouselIndex + 1) % slides.length;
            updateAlbumCarousel();
        }, 3200);
    }
}

function updateAlbumCarousel() {
    const slides = Array.from(document.querySelectorAll(".album-slide"));
    const total = slides.length;
    if (!total) return;

    slides.forEach((slide, index) => {
        let offset = index - albumCarouselIndex;
        if (offset > total / 2) offset -= total;
        if (offset < -total / 2) offset += total;

        const distance = Math.abs(offset);
        const translateX = offset * 96;
        const scale = offset === 0 ? 1.18 : Math.max(0.72, 1 - distance * 0.13);
        const opacity = distance > 3 ? 0 : Math.max(0.25, 1 - distance * 0.2);

        slide.classList.toggle("active", offset === 0);
        slide.classList.toggle("side", offset !== 0);
        slide.style.zIndex = String(100 - distance);
        slide.style.opacity = String(opacity);
        slide.style.transform = `translate(-50%, -50%) translateX(${translateX}px) scale(${scale}) rotateY(${offset * -16}deg)`;
    });
}

function renderStats(data) {
    const minutes = Number(data.total_minutes_listened) || 0;
    document.getElementById("stats-minutes").textContent = Math.round(minutes).toLocaleString();
    renderMetadataCoverage(data.metadata_coverage || {});

    const songs = Array.isArray(data.top_songs) ? data.top_songs : [];
    const artists = Array.isArray(data.top_artists) ? data.top_artists : [];
    const albums = Array.isArray(data.top_albums) ? data.top_albums : [];

    setupExpandableList(
        document.getElementById("stats-songs"),
        songs,
        (song, index) => createRankedItem(
            index + 1,
            song.title,
            song.artist,
            formatCount(song.count, "play"),
            song.genre || "",
        ),
        "No songs recognized yet.",
    );

    setupExpandableList(
        document.getElementById("stats-artists"),
        artists,
        (artist, index) => createRankedItem(index + 1, artist.name, "", formatCount(artist.count, "play")),
        "No artists recognized yet.",
    );

    setupExpandableList(
        document.getElementById("stats-albums"),
        albums,
        (album, index) => createRankedItem(index + 1, album.name, "", formatCount(album.count, "session")),
        "No album sessions recorded yet.",
    );

    renderGenreChart(data.radar_genres || data.top_genres || []);
    renderAlbumCarousel(data.top_album_covers || []);
}

async function loadStats() {
    try {
        const response = await fetch("/api/stats", { cache: "no-store" });
        if (!response.ok) throw new Error(`Statistics request failed: ${response.status}`);
        renderStats(await response.json());
    } catch (error) {
        console.error(error);
        renderStats({});
    }
}

document.addEventListener("DOMContentLoaded", loadStats);
