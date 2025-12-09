async function loadStats() {
    const songsList = document.getElementById("stats-songs");
    const artistsList = document.getElementById("stats-artists");
    const albumsList = document.getElementById("stats-albums");

    const setEmpty = () => {
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

        const { top_songs, top_artists, top_albums } = data;

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

        songsList.innerHTML = "";
        (top_songs || []).forEach((song, idx) => {
            const title = `${song.artist} – ${song.title}`;
            const subtitle = song.album ? song.album : "";
            const countText = `${song.count} plays`;
            songsList.appendChild(createItem(idx + 1, title, subtitle, countText));
        });

        artistsList.innerHTML = "";
        (top_artists || []).forEach((artist, idx) => {
            const title = artist.name;
            const countText = `${artist.count} plays`;
            artistsList.appendChild(createItem(idx + 1, title, "", countText));
        });

        albumsList.innerHTML = "";
        (top_albums || []).forEach((album, idx) => {
            const title = album.name;
            const countText = `${album.count} plays`;
            albumsList.appendChild(createItem(idx + 1, title, "", countText));
        });

    } catch (err) {
        console.error("Error loading stats:", err);
        setEmpty();
    }
}

document.addEventListener("DOMContentLoaded", loadStats);
