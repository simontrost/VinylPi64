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
            button.textContent = expanded ? "Show less" : "Show more";
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

function setShareFeedback(message, type = "") {
    const element = document.getElementById("stats-share-feedback");
    if (!element) return;
    element.textContent = message || "";
    element.classList.remove("is-error", "is-success", "is-muted");
    if (type) {
        element.classList.add(`is-${type}`);
    }
}

async function shareStatsSummary() {
    const button = document.getElementById("stats-share-button");
    if (!button) return;

    const originalHtml = button.innerHTML;
    button.disabled = true;
    button.classList.add("is-loading");
    button.innerHTML = "<span>Preparing…</span>";
    setShareFeedback("Creating your share image…", "muted");

    try {
        const response = await fetch("/api/stats/share-card", { cache: "no-store" });
        if (!response.ok) {
            throw new Error(`Share card request failed: ${response.status}`);
        }

        const blob = await response.blob();
        const file = new File([blob], "vinylpi-wrapped.png", { type: blob.type || "image/png" });

        const canUseWebShare =
            typeof navigator !== "undefined" &&
            typeof navigator.share === "function" &&
            typeof navigator.canShare === "function" &&
            navigator.canShare({ files: [file] });

        if (canUseWebShare) {
            await navigator.share({
                title: "My VinylPi summary",
                text: "My VinylPi listening summary.",
                files: [file],
            });
            setShareFeedback("Share card ready.", "success");
        } else {
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = "vinylpi-wrapped.png";
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(url), 1200);
            setShareFeedback("Image downloaded. You can now share it on social media.", "success");
        }
    } catch (error) {
        if (error && (error.name === "AbortError" || error.name === "NotAllowedError")) {
            setShareFeedback("Sharing cancelled.", "muted");
        } else {
            console.error(error);
            setShareFeedback("Could not create the share image right now.", "error");
        }
    } finally {
        button.disabled = false;
        button.classList.remove("is-loading");
        button.innerHTML = originalHtml;
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

document.addEventListener("DOMContentLoaded", () => {
    loadStats();
    const shareButton = document.getElementById("stats-share-button");
    if (shareButton) {
        shareButton.addEventListener("click", shareStatsSummary);
    }
});
