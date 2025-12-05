let CURRENT_CFG = null;

function rgbToHex(arr) {
    const [r, g, b] = arr;
    return "#" + [r, g, b]
        .map(x => x.toString(16).padStart(2, "0"))
        .join("");
}

function hexToRgb(hex) {
    hex = hex.replace("#", "");
    return [
        parseInt(hex.slice(0, 2), 16),
        parseInt(hex.slice(2, 4), 16),
        parseInt(hex.slice(4, 6), 16),
    ];
}

async function loadConfig() {
    const r = await fetch("/api/config");
    const cfg = await r.json();
    CURRENT_CFG = cfg;

    const image = cfg.image || {};
    const fallback = cfg.fallback || {};
    const divoom = cfg.divoom || {};
    const discovery = (divoom.discovery || {});
    const debug = cfg.debug || {};

    // Display
    document.getElementById("textColor").value =
        rgbToHex(image.text_color || [255, 255, 255]);
    document.getElementById("bgColor").value =
        rgbToHex(image.manual_bg_color || [0, 0, 0]);
    document.getElementById("uppercase").checked =
        !!image.uppercase;
    document.getElementById("useDynamicBg").checked =
        !!image.use_dynamic_bg;
    document.getElementById("useDynamicText").checked =
        !!image.use_dynamic_text_color;
    document.getElementById("marqueeSpeed").value =
        image.marquee_speed ?? 20;

    // Fallback
    document.getElementById("fallbackEnabled").checked =
        !!fallback.enabled;
    document.getElementById("fallbackImage").value =
        fallback.image_path || "";

    // Pixoo/Netzwerk
    document.getElementById("divoomIp").value =
        divoom.ip || "";
    document.getElementById("discoveryEnabled").checked =
        !!discovery.enabled;
    document.getElementById("subnetPrefix").value =
        discovery.subnet_prefix || "";
    document.getElementById("ipRangeStart").value =
        discovery.ip_range_start ?? "";
    document.getElementById("ipRangeEnd").value =
        discovery.ip_range_end ?? "";

    // Debug
    document.getElementById("debugLogs").checked =
        !!debug.logs;
}

document.getElementById("settings-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!CURRENT_CFG) return;

    const cfg = CURRENT_CFG;

    cfg.image = cfg.image || {};
    cfg.fallback = cfg.fallback || {};
    cfg.divoom = cfg.divoom || {};
    cfg.divoom.discovery = cfg.divoom.discovery || {};
    cfg.debug = cfg.debug || {};

    // Display
    cfg.image.text_color =
        hexToRgb(document.getElementById("textColor").value);
    cfg.image.manual_bg_color =
        hexToRgb(document.getElementById("bgColor").value);
    cfg.image.uppercase =
        document.getElementById("uppercase").checked;
    cfg.image.use_dynamic_bg =
        document.getElementById("useDynamicBg").checked;
    cfg.image.use_dynamic_text_color =
        document.getElementById("useDynamicText").checked;
    cfg.image.marquee_speed =
        parseInt(document.getElementById("marqueeSpeed").value) || 20;

    // Fallback
    cfg.fallback.enabled =
        document.getElementById("fallbackEnabled").checked;
    cfg.fallback.image_path =
        document.getElementById("fallbackImage").value;

    // Pixoo/Netzwerk
    cfg.divoom.ip =
        document.getElementById("divoomIp").value;
    cfg.divoom.discovery.enabled =
        document.getElementById("discoveryEnabled").checked;
    cfg.divoom.discovery.subnet_prefix =
        document.getElementById("subnetPrefix").value;
    cfg.divoom.discovery.ip_range_start =
        parseInt(document.getElementById("ipRangeStart").value) || 100;
    cfg.divoom.discovery.ip_range_end =
        parseInt(document.getElementById("ipRangeEnd").value) || 199;

    // Debug
    cfg.debug.logs =
        document.getElementById("debugLogs").checked;

    await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg),
    });

    alert("Einstellungen gespeichert.");
});

loadConfig();
