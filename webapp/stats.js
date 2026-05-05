async function loadStats() {
    const minutesEl = document.getElementById("stats-minutes");
    const songsList = document.getElementById("stats-songs");
    const artistsList = document.getElementById("stats-artists");
    const albumsList = document.getElementById("stats-albums");

    const setEmpty = () => {
        songsList.innerHTML = "";
        artistsList.innerHTML = "";
        albumsList.innerHTML = "";
        if (minutesEl) minutesEl.textContent = "0";
        const msg = document.createElement("li");
        msg.className = "stats-empty";
        msg.textContent = "No data yet, play a record!🎶";

        songsList.appendChild(msg.cloneNode(true));
        artistsList.appendChild(msg.cloneNode(true));
        albumsList.appendChild(msg.cloneNode(true));
    };

    try {
        const res = await fetch("/api/stats");
        if (!res.ok) {
            setEmpty();
            return;
        }

        const data = await res.json();
        const { top_songs, top_artists, top_albums, total_minutes_listened } = data;

        if (minutesEl) {
            const mins = Number.isFinite(total_minutes_listened) ? total_minutes_listened : 0;
            minutesEl.textContent = String(mins);
        }

        const { top_tags, radar_tags } = data;
        renderGenreCharts(top_tags || [], radar_tags || []);
        renderAlbumCarousel(data.top_album_covers || []);
        if ((!top_songs || top_songs.length === 0) &&
            (!top_artists || top_artists.length === 0) &&
            (!top_albums || top_albums.length === 0)) {
            setEmpty();
            return;
        }

        const createItem = (rank, title, subtitle, countText) => {
            const li = document.createElement("li");
            li.className = "stats-item";

            const rankSpan = document.createElement("span");
            rankSpan.className = "stats-rank";
            rankSpan.textContent = `#${rank}`;

            const textDiv = document.createElement("div");
            textDiv.className = "stats-text";

            const mainLine = document.createElement("div");
            mainLine.className = "stats-main";
            mainLine.textContent = title;

            if (subtitle) {
                const subLine = document.createElement("div");
                subLine.className = "stats-sub";
                subLine.textContent = subtitle;
                textDiv.appendChild(mainLine);
                textDiv.appendChild(subLine);
            } else {
                textDiv.appendChild(mainLine);
            }

            const badge = document.createElement("span");
            badge.className = "stats-badge";
            badge.textContent = countText;

            li.appendChild(rankSpan);
            li.appendChild(textDiv);
            li.appendChild(badge);

            return li;
        };

        const MAX_VISIBLE = 5;

        const setupExpandableList = (listElement, items, renderItem) => {
            listElement.innerHTML = "";
            if (!items || items.length === 0) {
                return;
            }

            let expanded = false;

            const render = () => {
                listElement.innerHTML = "";

                const visibleCount = expanded
                    ? items.length
                    : Math.min(items.length, MAX_VISIBLE);

                for (let i = 0; i < visibleCount; i++) {
                    listElement.appendChild(renderItem(items[i], i));
                }

                if (items.length > MAX_VISIBLE) {
                    const toggleLi = document.createElement("li");
                    toggleLi.className = "stats-toggle-wrapper";

                    const btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = "stats-toggle";
                    btn.textContent = expanded ? "Less" : "More";

                    btn.addEventListener("click", () => {
                        expanded = !expanded;
                        render();
                    });

                    toggleLi.appendChild(btn);
                    listElement.appendChild(toggleLi);
                }
            };

            render();
        };

        // Songs
        setupExpandableList(songsList, top_songs || [], (song, idx) => {
            const title = song.title;
            const subtitle = song.artist || "";
            const countText = `${song.count} plays`;
            return createItem(idx + 1, title, subtitle, countText);
        });

        // Artists
        setupExpandableList(artistsList, top_artists || [], (artist, idx) => {
            const title = artist.name;
            const countText = `${artist.count} plays`;
            return createItem(idx + 1, title, "", countText);
        });

        // Albums
        setupExpandableList(albumsList, top_albums || [], (album, idx) => {
            const title = album.name;
            const countText = `${album.count} plays`;
            return createItem(idx + 1, title, "", countText);
        });


    } catch (err) {
        console.error("Error loading stats:", err);
        setEmpty();
    }
}

document.addEventListener("DOMContentLoaded", () => {
    loadStats();
});

let radarChart = null;
function renderGenreCharts(topTags, radarTags) {
    const radarCanvas = document.getElementById("genre-radar");
    if (!radarCanvas) return;

    const radarLabels = radarTags.map(t => t.name);
    const radarValues = radarTags.map(t => t.count);

    if (radarChart) radarChart.destroy();

    radarChart = new Chart(radarCanvas, {
        type: "radar",
        data: {
            labels: radarLabels,
            datasets: [{
                data: radarValues,
                fill: true,
                backgroundColor: "rgba(113, 41, 195, 0.3)",
                borderColor: "rgba(221, 17, 125, 1)",
                pointBackgroundColor: "rgba(255, 140, 38, 1)"
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                r: {
                    min: 0,
                    ticks: {
                        display: false
                    },
                    grid: {
                        color: "rgba(255,255,255,0.15)"
                    },
                    angleLines: {
                        color: "rgba(255,255,255,0.15)"
                    },
                    pointLabels: {
                        color: "#e6e6e6",
                        font: {
                            size: 11
                        }
                    }
                }
            }
        }
    });
}
let albumCarouselTimer = null;
let albumCarouselIndex = 0;
let albumCarouselItems = [];

function renderAlbumCarousel(albums) {
    const root = document.getElementById("album-carousel");
    if (!root) return;

    root.innerHTML = "";

    albumCarouselItems = albums.filter(a => a.cover_url).slice(0, 10);

    if (albumCarouselItems.length === 0) {
        root.innerHTML = `<div class="stats-empty">No album covers yet</div>`;
        return;
    }

    albumCarouselItems.forEach((album, index) => {
        const el = document.createElement("div");
        el.className = "album-slide";
        el.innerHTML = `
            <img src="${album.cover_url}" alt="${album.name}">
            <div class="album-slide-title">${album.name} · ${album.count} plays</div>
        `;
        root.appendChild(el);
    });

    updateAlbumCarousel();

    if (albumCarouselTimer) clearInterval(albumCarouselTimer);
    albumCarouselTimer = setInterval(() => {
        albumCarouselIndex = (albumCarouselIndex + 1) % albumCarouselItems.length;
        updateAlbumCarousel();
    }, 2800);
}

function updateAlbumCarousel() {
    const slides = document.querySelectorAll(".album-slide");
    const total = slides.length;

    slides.forEach((slide, i) => {
        let offset = i - albumCarouselIndex;

        if (offset > total / 2) offset -= total;
        if (offset < -total / 2) offset += total;

        const abs = Math.abs(offset);
        const x = offset * 95;
        const scale = offset === 0 ? 1.25 : Math.max(0.72, 1 - abs * 0.13);
        const rotateY = offset * -18;
        const opacity = abs > 3 ? 0 : 1 - abs * 0.18;
        const z = 100 - abs;

        slide.classList.toggle("active", offset === 0);
        slide.classList.toggle("side", offset !== 0);

        slide.style.zIndex = z;
        slide.style.opacity = opacity;
        slide.style.transform = `
            translate(-50%, -50%)
            translateX(${x}px)
            scale(${scale})
            rotateY(${rotateY}deg)
        `;
    });
}
