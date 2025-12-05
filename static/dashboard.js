async function loadStatus() {
    try {
        const r = await fetch("/api/status");
        const st = await r.json();

        if (st.error) {
            document.getElementById("title").innerText = "Keine Daten";
            return;
        }

        document.getElementById("title").innerText  = st.title;
        document.getElementById("artist").innerText = st.artist;
        document.getElementById("album").innerText  = st.album || "";

        if (st.cover_url) {
            document.getElementById("cover").src = st.cover_url;
        }

    } catch (e) {
        document.getElementById("title").innerText = "Fehler";
    }
}

async function loadConfig() {
    const r = await fetch("/api/config");
    const cfg = await r.json();

    document.getElementById("textColor").value =
        rgbToHex(cfg.image.text_color);

    document.getElementById("bgColor").value =
        rgbToHex(cfg.image.manual_bg_color);

    document.getElementById("dynBg").checked = cfg.image.use_dynamic_bg;
    document.getElementById("dynText").checked = cfg.image.use_dynamic_text_color;
}

document.getElementById("saveBtn").onclick = async () => {
    const cfg = {
        image: {
            text_color: hexToRgb(document.getElementById("textColor").value),
            manual_bg_color: hexToRgb(document.getElementById("bgColor").value),
            use_dynamic_bg: document.getElementById("dynBg").checked,
            use_dynamic_text_color: document.getElementById("dynText").checked,
        },
        fallback: {
            image_path: "assets/fallback.png"
        }
    };

    await fetch("/api/config", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(cfg)
    });

    alert("Gespeichert!");
};

function rgbToHex([r, g, b]) {
    return "#" + [r, g, b].map(x =>
        x.toString(16).padStart(2, "0")
    ).join("");
}

function hexToRgb(hex) {
    hex = hex.replace("#", "");
    return [
        parseInt(hex.substring(0,2), 16),
        parseInt(hex.substring(2,4), 16),
        parseInt(hex.substring(4,6), 16),
    ];
}

loadStatus();
loadConfig();
