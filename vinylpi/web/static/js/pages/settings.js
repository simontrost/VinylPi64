let CURRENT_CFG = null;
let toastTimer = null;
let discogsStatusTimer = null;

function showToast(message, isError = false) {
    const toast = document.getElementById("settingsToast");
    if (!toast) return;

    toast.textContent = message;
    toast.style.borderColor = isError
        ? "rgba(239, 68, 68, 0.55)"
        : "rgba(34, 197, 94, 0.45)";
    toast.classList.add("show");

    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove("show"), 3200);
}

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

function syncManualColorState(toggleId, colorId) {
    const toggle = document.getElementById(toggleId);
    const color = document.getElementById(colorId);
    if (!toggle || !color) return;

    color.disabled = toggle.checked;
    color.setAttribute("aria-disabled", String(toggle.checked));
}

function syncAllManualColorStates() {
    syncManualColorState("useDynamicBg", "bgColor");
    syncManualColorState("useDynamicText", "textColor");
}

function syncAdaptiveSampleState() {
    const enabled = document.getElementById("adaptiveSampleEnabled")?.checked ?? false;
    const details = document.querySelector('[data-setting-row="adaptive-sample-details"]');
    if (!details) return;
    details.classList.toggle("setting-disabled", !enabled);
    details.querySelectorAll("input").forEach((input) => {
        input.disabled = !enabled;
    });
}

function setDependentState(toggleId, rowName, enabledOverride = null) {
    const toggle = document.getElementById(toggleId);
    const details = document.querySelector(`[data-setting-row="${rowName}"]`);
    if (!details) return;

    const enabled = enabledOverride === null
        ? Boolean(toggle?.checked)
        : Boolean(enabledOverride);
    details.classList.toggle("setting-disabled", !enabled);
    details.setAttribute("aria-disabled", String(!enabled));
    details.querySelectorAll("input, button, select, textarea").forEach((control) => {
        control.disabled = !enabled;
    });
}

function syncFallbackStates() {
    const normalEnabled = Boolean(document.getElementById("fallbackEnabled")?.checked);
    const turnEnabled = Boolean(document.getElementById("sideFlipEnabled")?.checked);
    setDependentState("fallbackEnabled", "fallback-normal-details", normalEnabled);
    setDependentState("sideFlipEnabled", "fallback-turn-details", turnEnabled);
    setDependentState("fallbackEnabled", "fallback-shared-details", normalEnabled || turnEnabled);
}

function syncDependentSettingStates() {
    syncAdaptiveSampleState();
    syncFallbackStates();
    setDependentState("discoveryEnabled", "discovery-details");
    setDependentState("useHA", "ha-details");
    setDependentState("debugLogs", "debug-details");
    setDependentState("discogsEnabled", "discogs-details");
}

function setSelectedImagePath(inputId, pathId, path) {
    const normalized = String(path || "").trim();
    const input = document.getElementById(inputId);
    const label = document.getElementById(pathId);
    if (input) input.value = normalized;
    if (label) {
        label.textContent = normalized || "No image selected";
        label.title = normalized;
    }
}

function setSelectedFontPath(path) {
    const normalized = String(path || "").trim();
    const input = document.getElementById("imageFontPath");
    const label = document.getElementById("imageFontPathLabel");
    if (input) input.value = normalized;
    if (label) {
        label.textContent = normalized || "No font selected";
        label.title = normalized;
    }
    loadDisplayPreviewFont(normalized);
}


const DISPLAY_LAYOUT_PRESETS = {
    classic: {
        showCover: true, showArtist: true, showTitle: true, showAlbum: false,
        topMargin: 1, coverSize: 46, coverGap: 3, lineGap: 3, fontSize: 5,
    },
    "large-text": {
        showCover: true, showArtist: true, showTitle: true, showAlbum: false,
        topMargin: 1, coverSize: 42, coverGap: 3, lineGap: 2, fontSize: 7,
    },
    "album-info": {
        showCover: true, showArtist: true, showTitle: true, showAlbum: true,
        topMargin: 1, coverSize: 37, coverGap: 2, lineGap: 2, fontSize: 5,
    },
    "cover-only": {
        showCover: true, showArtist: false, showTitle: false, showAlbum: false,
        topMargin: 0, coverSize: 64, coverGap: 0, lineGap: 0, fontSize: 5,
    },
    "text-only": {
        showCover: false, showArtist: true, showTitle: true, showAlbum: true,
        topMargin: 10, coverSize: 46, coverGap: 0, lineGap: 4, fontSize: 10,
    },
};

const DISPLAY_LAYOUT_FIELDS = {
    showCover: "imageShowCover",
    showArtist: "imageShowArtist",
    showTitle: "imageShowTitle",
    showAlbum: "imageShowAlbum",
    topMargin: "imageTopMargin",
    coverSize: "imageCoverSize",
    coverGap: "imageMarginImageText",
    lineGap: "imageLineSpacingMargin",
    fontSize: "imageFontSize",
};

const DISPLAY_LAYOUT_OUTPUTS = {
    topMargin: "imageTopMarginValue",
    coverSize: "imageCoverSizeValue",
    coverGap: "imageMarginImageTextValue",
    lineGap: "imageLineSpacingMarginValue",
    fontSize: "imageFontSizeValue",
};

let DISPLAY_PREVIEW_TRACK = {
    artist: "ARTIST",
    title: "TRACK TITLE",
    album: "ALBUM",
};
let DISPLAY_PREVIEW_IMAGE = null;
let DISPLAY_PREVIEW_IMAGE_FAILED = false;
let DISPLAY_PREVIEW_FONT_FAMILY = "monospace";
let DISPLAY_PREVIEW_FONT_REQUEST = 0;

async function loadDisplayPreviewFont(path) {
    const requestId = ++DISPLAY_PREVIEW_FONT_REQUEST;
    const filename = String(path || "").split(/[\\/]/).pop();
    if (!filename || typeof FontFace === "undefined" || !document.fonts) {
        DISPLAY_PREVIEW_FONT_FAMILY = "monospace";
        renderDisplayPreview();
        return;
    }

    const family = `VinylPiPreview${requestId}`;
    try {
        const face = new FontFace(
            family,
            `url(/api/font-file/${encodeURIComponent(filename)})`,
        );
        await face.load();
        if (requestId !== DISPLAY_PREVIEW_FONT_REQUEST) return;
        document.fonts.add(face);
        DISPLAY_PREVIEW_FONT_FAMILY = `"${family}"`;
    } catch (error) {
        if (requestId !== DISPLAY_PREVIEW_FONT_REQUEST) return;
        DISPLAY_PREVIEW_FONT_FAMILY = "monospace";
        console.debug("Display preview font unavailable", error);
    }
    renderDisplayPreview();
}

function clampDisplayNumber(value, minimum, maximum, fallback) {
    const parsed = Number.parseInt(value, 10);
    const safe = Number.isFinite(parsed) ? parsed : fallback;
    return Math.max(minimum, Math.min(maximum, safe));
}

function readDisplayDesigner() {
    const checked = (key, fallback) => {
        const element = document.getElementById(DISPLAY_LAYOUT_FIELDS[key]);
        return element ? Boolean(element.checked) : fallback;
    };
    const value = (key, fallback) => {
        const element = document.getElementById(DISPLAY_LAYOUT_FIELDS[key]);
        return element ? element.value : fallback;
    };

    return {
        showCover: checked("showCover", true),
        showArtist: checked("showArtist", true),
        showTitle: checked("showTitle", true),
        showAlbum: checked("showAlbum", false),
        topMargin: clampDisplayNumber(value("topMargin", 1), 0, 16, 1),
        coverSize: clampDisplayNumber(value("coverSize", 46), 12, 64, 46),
        coverGap: clampDisplayNumber(value("coverGap", 3), 0, 8, 3),
        lineGap: clampDisplayNumber(value("lineGap", 3), 0, 8, 3),
        fontSize: clampDisplayNumber(value("fontSize", 5), 3, 12, 5),
    };
}

function displayTextCount(state) {
    return [state.showArtist, state.showTitle, state.showAlbum].filter(Boolean).length;
}

function displayUsedHeight(state) {
    const textCount = displayTextCount(state);
    let used = state.topMargin;
    if (state.showCover) used += state.coverSize;
    if (state.showCover && textCount) used += state.coverGap;
    if (textCount) {
        used += textCount * state.fontSize;
        used += Math.max(0, textCount - 1) * state.lineGap;
    }
    return used;
}

function writeDisplayDesigner(state) {
    for (const [key, id] of Object.entries(DISPLAY_LAYOUT_FIELDS)) {
        const element = document.getElementById(id);
        if (!element) continue;
        if (key.startsWith("show")) element.checked = Boolean(state[key]);
        else element.value = String(state[key]);
    }
}

function fitDisplayDesigner(state, changedKey = null) {
    state = { ...state };
    const notes = [];
    const visibleKeys = ["showCover", "showArtist", "showTitle", "showAlbum"];
    if (!visibleKeys.some((key) => state[key])) {
        if (changedKey && visibleKeys.includes(changedKey)) state[changedKey] = true;
        else state.showTitle = true;
        notes.push("At least one display element must stay enabled.");
    }

    const textCount = () => displayTextCount(state);
    const canShrink = (key) => {
        if (key === "coverSize") return state.showCover && state.coverSize > 12;
        if (key === "topMargin") return state.topMargin > 0;
        if (key === "coverGap") return state.showCover && textCount() > 0 && state.coverGap > 0;
        if (key === "lineGap") return textCount() > 1 && state.lineGap > 0;
        if (key === "fontSize") return textCount() > 0 && state.fontSize > 3;
        return false;
    };

    let order;
    if (changedKey === "coverSize") {
        order = ["topMargin", "coverGap", "lineGap", "coverSize", "fontSize"];
    } else if (changedKey === "fontSize") {
        order = ["coverSize", "topMargin", "coverGap", "lineGap", "fontSize"];
    } else {
        order = ["coverSize", "topMargin", "coverGap", "lineGap", "fontSize"];
        if (changedKey && order.includes(changedKey)) {
            order = order.filter((key) => key !== changedKey).concat(changedKey);
        }
    }

    const before = { ...state };
    let guard = 256;
    while (displayUsedHeight(state) > 64 && guard-- > 0) {
        const key = order.find(canShrink);
        if (!key) break;
        state[key] -= 1;
    }

    const changed = [];
    for (const key of ["coverSize", "fontSize", "topMargin", "coverGap", "lineGap"]) {
        if (state[key] !== before[key]) changed.push(`${key} ${before[key]}→${state[key]} px`);
    }
    if (changed.length) notes.push(`Auto-fit adjusted ${changed.join(", ")}.`);
    return { state, note: notes.join(" ") };
}

function setDisplayDesignerEnabledState(state) {
    const textCount = displayTextCount(state);
    const rows = {
        cover: state.showCover,
        text: textCount > 0,
        "cover-gap": state.showCover && textCount > 0,
        "line-gap": textCount > 1,
    };
    for (const [name, enabled] of Object.entries(rows)) {
        const row = document.querySelector(`[data-display-control="${name}"]`);
        if (!row) continue;
        row.classList.toggle("is-disabled", !enabled);
        row.querySelectorAll("input").forEach((input) => { input.disabled = !enabled; });
    }
}

function updateDisplayDesignerOutputs(state) {
    for (const [key, id] of Object.entries(DISPLAY_LAYOUT_OUTPUTS)) {
        const output = document.getElementById(id);
        if (output) output.textContent = `${state[key]} px`;
    }

    const used = displayUsedHeight(state);
    const usage = document.getElementById("displayFitUsage");
    const status = document.getElementById("displayFitStatus");
    const bar = document.getElementById("displayFitBar");
    if (usage) usage.textContent = `${used} / 64 px`;
    if (status) status.textContent = used <= 64 ? "Fits display" : "Layout too tall";
    if (bar) bar.style.width = `${Math.min(100, Math.max(0, (used / 64) * 100))}%`;
}

function currentDisplayColors() {
    const dynamicBg = document.getElementById("useDynamicBg")?.checked ?? true;
    const dynamicText = document.getElementById("useDynamicText")?.checked ?? true;
    const inverted = document.getElementById("invertDynamicColors")?.checked ?? false;
    const manualBg = document.getElementById("bgColor")?.value || "#000000";
    const manualText = document.getElementById("textColor")?.value || "#ffffff";

    // Automatic colors depend on cover-art analysis performed on the Pi. The
    // designer uses representative colors while preserving manual colors exactly.
    const autoCoverColor = "#31536b";
    const autoContrast = "#ffffff";
    return {
        bg: dynamicBg ? (inverted ? autoContrast : autoCoverColor) : manualBg,
        text: dynamicText ? (inverted ? autoCoverColor : autoContrast) : manualText,
    };
}

function renderDisplayPreview(state = readDisplayDesigner()) {
    const canvas = document.getElementById("displayPreview");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const colors = currentDisplayColors();
    ctx.save();
    ctx.clearRect(0, 0, 64, 64);
    ctx.fillStyle = colors.bg;
    ctx.fillRect(0, 0, 64, 64);
    ctx.beginPath();
    ctx.rect(0, 0, 64, 64);
    ctx.clip();
    ctx.imageSmoothingEnabled = false;

    let y = state.topMargin;
    if (state.showCover) {
        const size = state.coverSize;
        const x = Math.floor((64 - size) / 2);
        if (DISPLAY_PREVIEW_IMAGE && DISPLAY_PREVIEW_IMAGE.complete && !DISPLAY_PREVIEW_IMAGE_FAILED) {
            const iw = DISPLAY_PREVIEW_IMAGE.naturalWidth || DISPLAY_PREVIEW_IMAGE.width;
            const ih = DISPLAY_PREVIEW_IMAGE.naturalHeight || DISPLAY_PREVIEW_IMAGE.height;
            const side = Math.min(iw, ih);
            const sx = Math.floor((iw - side) / 2);
            const sy = Math.floor((ih - side) / 2);
            ctx.drawImage(DISPLAY_PREVIEW_IMAGE, sx, sy, side, side, x, y, size, size);
        } else {
            const gradient = ctx.createLinearGradient(x, y, x + size, y + size);
            gradient.addColorStop(0, "#ef2d8f");
            gradient.addColorStop(1, "#f5c542");
            ctx.fillStyle = gradient;
            ctx.fillRect(x, y, size, size);
        }
        y += size;
    }

    const lines = [];
    if (state.showArtist) lines.push(DISPLAY_PREVIEW_TRACK.artist || "ARTIST");
    if (state.showTitle) lines.push(DISPLAY_PREVIEW_TRACK.title || "TRACK TITLE");
    if (state.showAlbum) lines.push(DISPLAY_PREVIEW_TRACK.album || "ALBUM");
    if (state.showCover && lines.length) y += state.coverGap;

    const uppercase = document.getElementById("imageUppercase")?.checked ?? true;
    ctx.fillStyle = colors.text;
    ctx.font = `${state.fontSize}px ${DISPLAY_PREVIEW_FONT_FAMILY}, monospace`;
    ctx.textBaseline = "top";

    lines.forEach((rawText, index) => {
        const text = uppercase ? String(rawText).toUpperCase() : String(rawText);
        const width = ctx.measureText(text).width;
        const x = width <= 63 ? Math.max(0, Math.floor((64 - width) / 2)) : 1;
        ctx.fillText(text, x, y, Math.max(64, width));
        y += state.fontSize;
        if (index < lines.length - 1) y += state.lineGap;
    });
    ctx.restore();
}

function markDisplayPreset(state) {
    document.querySelectorAll("[data-display-preset]").forEach((button) => {
        const preset = DISPLAY_LAYOUT_PRESETS[button.dataset.displayPreset];
        const matches = preset && Object.entries(preset).every(([key, value]) => state[key] === value);
        button.classList.toggle("is-active", Boolean(matches));
    });
}

function syncDisplayDesigner({ changedKey = null, announce = false, note = "" } = {}) {
    const fitted = fitDisplayDesigner(readDisplayDesigner(), changedKey);
    writeDisplayDesigner(fitted.state);
    setDisplayDesignerEnabledState(fitted.state);
    updateDisplayDesignerOutputs(fitted.state);
    renderDisplayPreview(fitted.state);
    markDisplayPreset(fitted.state);

    const noteElement = document.getElementById("displayConstraintNote");
    const message = fitted.note || note || "The designer automatically keeps the vertical layout inside 64 pixels. Long text scrolls horizontally.";
    if (noteElement) noteElement.textContent = message;
    if (announce && fitted.note) showToast(fitted.note);
    return fitted.state;
}

function applyDisplayPreset(name) {
    const preset = DISPLAY_LAYOUT_PRESETS[name];
    if (!preset) return;
    writeDisplayDesigner(preset);
    syncDisplayDesigner({ note: `${name.replace(/-/g, " ")} layout applied.` });
}

async function loadDisplayPreviewTrack() {
    try {
        const response = await fetch("/api/status", { cache: "no-store" });
        const status = await response.json();
        if (response.ok && status && !status.error && status.status !== null) {
            DISPLAY_PREVIEW_TRACK = {
                artist: status.artist || DISPLAY_PREVIEW_TRACK.artist,
                title: status.title || DISPLAY_PREVIEW_TRACK.title,
                album: status.album || DISPLAY_PREVIEW_TRACK.album,
            };
        }

        const image = new Image();
        DISPLAY_PREVIEW_IMAGE_FAILED = false;
        image.onload = () => {
            DISPLAY_PREVIEW_IMAGE = image;
            renderDisplayPreview();
        };
        image.onerror = () => {
            if (image.src.endsWith("/static/images/logo.png")) {
                DISPLAY_PREVIEW_IMAGE_FAILED = true;
                renderDisplayPreview();
                return;
            }
            image.src = "/static/images/logo.png";
        };
        image.src = (response.ok && status?.cover_url) ? status.cover_url : "/static/images/logo.png";
    } catch (error) {
        console.debug("Display preview track unavailable", error);
        renderDisplayPreview();
    }
}


function formatDiscogsTimestamp(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds <= 0) return "Never synced";
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    }).format(new Date(seconds * 1000));
}

function renderDiscogsStatus(status) {
    const connected = !!status.connected;
    const syncing = !!status.syncing;
    const dot = document.getElementById("discogsStatusDot");
    const title = document.getElementById("discogsStatusTitle");
    const copy = document.getElementById("discogsStatusCopy");
    const connect = document.getElementById("discogsConnect");
    const sync = document.getElementById("discogsSync");
    const progress = document.getElementById("discogsProgress");
    const progressBar = document.getElementById("discogsProgressBar");
    const progressCopy = document.getElementById("discogsProgressCopy");

    if (dot) dot.className = `discogs-status-dot ${connected ? "connected" : ""} ${syncing ? "syncing" : ""}`;
    if (title) {
        title.textContent = connected && status.username
            ? `Connected as ${status.username}`
            : connected
                ? "Token configured"
                : "Token not configured";
    }
    if (copy) {
        if (status.last_error) {
            copy.textContent = status.last_error;
        } else if (connected && status.username) {
            copy.textContent = `${formatDiscogsTimestamp(status.last_synced_at)} · ${status.sync_status || "ready"}`;
        } else if (connected) {
            copy.textContent = "Token found in vinylpi.env. Check the connection or start a sync.";
        } else {
            copy.textContent = "Set DISCOGS_API_TOKEN in vinylpi.env and restart VinylPi.";
        }
    }
    const releases = document.getElementById("discogsReleaseCount");
    const tracks = document.getElementById("discogsTrackCount");
    if (releases) releases.textContent = String(status.releases_count || 0);
    if (tracks) tracks.textContent = String(status.tracks_count || 0);
    if (connect) connect.disabled = syncing;
    if (sync) sync.disabled = !connected || syncing;

    if (progress) progress.classList.toggle("hidden", !syncing);
    if (syncing) {
        const current = Number(status.current || 0);
        const total = Number(status.total || 0);
        const percent = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 4;
        if (progressBar) progressBar.style.width = `${percent}%`;
        if (progressCopy) progressCopy.textContent = status.message || "Synchronizing collection…";
    }
}

async function loadDiscogsStatus() {
    try {
        const response = await fetch("/api/discogs/status", { cache: "no-store" });
        const status = await response.json();
        if (!response.ok || !status.ok) throw new Error(status.error || "Discogs status failed");
        renderDiscogsStatus(status);
        if (discogsStatusTimer) window.clearTimeout(discogsStatusTimer);
        discogsStatusTimer = window.setTimeout(loadDiscogsStatus, status.syncing ? 1000 : 8000);
    } catch (error) {
        console.error(error);
        if (discogsStatusTimer) window.clearTimeout(discogsStatusTimer);
        discogsStatusTimer = window.setTimeout(loadDiscogsStatus, 10000);
    }
}

async function connectDiscogs() {
    try {
        const response = await fetch("/api/discogs/connect", { method: "POST" });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "Connection failed");
        showToast(`Discogs token is valid. Connected as ${data.username}.`);
        await loadConfig();
        await loadDiscogsStatus();
    } catch (error) {
        console.error(error);
        showToast(error.message || "Discogs connection failed.", true);
    }
}

async function startDiscogsSync() {
    try {
        const response = await fetch("/api/discogs/sync", { method: "POST" });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "Sync could not start");
        showToast(data.started === false ? data.message : "Discogs synchronization started.");
        await loadDiscogsStatus();
    } catch (error) {
        console.error(error);
        showToast(error.message || "Discogs synchronization failed.", true);
    }
}


document.addEventListener("DOMContentLoaded", () => {
  const galleryControls = [];

  async function reloadOpenGalleries() {
    await Promise.all(galleryControls
      .filter((control) => !control.gallery.classList.contains("hidden"))
      .map((control) => control.loadGallery()));
  }

  function setupFallbackImageControl({
    kind, uploadId, inputId, pathId, openId, galleryId, label,
  }) {
    const upload = document.getElementById(uploadId);
    const pathInput = document.getElementById(inputId);
    const openButton = document.getElementById(openId);
    const gallery = document.getElementById(galleryId);
    if (!upload || !pathInput || !openButton || !gallery) return null;

    const control = { kind, gallery, loadGallery: null };

    control.loadGallery = async () => {
      gallery.innerHTML = "Loading images …";
      try {
        const response = await fetch(`/api/fallback-images?kind=${encodeURIComponent(kind)}`);
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "Error");

        const images = data.images || [];
        if (!images.length) {
          gallery.innerHTML = "<p>No fallback images available.</p>";
          return;
        }

        gallery.replaceChildren();
        images.forEach((image) => {
          const item = document.createElement("div");
          const selected = image.path === pathInput.value;
          item.className = `gallery-item selectable${selected ? " current" : ""}`;
          item.tabIndex = 0;
          item.setAttribute("role", "button");
          item.setAttribute("aria-label", `Use ${image.filename} as ${label}`);

          const thumbnail = document.createElement("img");
          thumbnail.src = image.url;
          thumbnail.alt = image.filename;

          const name = document.createElement("div");
          name.className = "gallery-filename";
          name.textContent = image.filename;

          const selectImage = () => {
            setSelectedImagePath(inputId, pathId, image.path);
            gallery.querySelectorAll(".gallery-item").forEach((entry) => entry.classList.remove("current"));
            item.classList.add("current");
            showToast(`${label} selected: ${image.filename}`);
          };

          item.addEventListener("click", selectImage);
          item.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              selectImage();
            }
          });

          const deleteButton = document.createElement("button");
          deleteButton.type = "button";
          deleteButton.className = "gallery-delete";
          deleteButton.textContent = "Delete";
          deleteButton.addEventListener("click", async (event) => {
            event.stopPropagation();
            if (!confirm(`Delete "${image.filename}"?`)) return;

            const response = await fetch(`/api/fallback-image/${encodeURIComponent(image.filename)}`, {
              method: "DELETE",
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok || !result.ok) {
              showToast("Deletion failed: " + (result.error || "unknown error"), true);
              return;
            }

            galleryControls.forEach((entry) => {
              const selectedInput = document.getElementById(entry.inputId);
              if (selectedInput?.value === image.path) {
                setSelectedImagePath(entry.inputId, entry.pathId, "");
              }
            });
            await reloadOpenGalleries();
            showToast(`Deleted ${image.filename}.`);
          });

          item.append(thumbnail, name, deleteButton);
          gallery.appendChild(item);
        });
      } catch (error) {
        console.error(error);
        gallery.innerHTML = "<p>Error loading gallery.</p>";
      }
    };

    control.inputId = inputId;
    control.pathId = pathId;
    galleryControls.push(control);

    upload.addEventListener("change", async (event) => {
      const file = event.target.files?.[0];
      if (!file) return;

      const formData = new FormData();
      formData.append("file", file);
      try {
        const response = await fetch(`/api/fallback-image?kind=${encodeURIComponent(kind)}`, {
          method: "POST",
          body: formData,
        });
        const data = await response.json();
        if (!response.ok || !data.ok || !data.image_path) {
          throw new Error(data.error || "unknown error");
        }
        setSelectedImagePath(inputId, pathId, data.image_path);
        upload.value = "";
        await reloadOpenGalleries();
        showToast(`${label} uploaded and selected.`);
      } catch (error) {
        console.error(error);
        showToast(`Upload failed: ${error.message || "network error"}`, true);
      }
    });

    openButton.addEventListener("click", async () => {
      gallery.classList.toggle("hidden");
      openButton.textContent = gallery.classList.contains("hidden") ? "Open gallery" : "Close gallery";
      if (!gallery.classList.contains("hidden")) await control.loadGallery();
    });

    return control;
  }

  const fontUpload = document.getElementById("fontUpload");
  const fontPathInput = document.getElementById("imageFontPath");
  const openFontGallery = document.getElementById("openFontGallery");
  const fontGallery = document.getElementById("fontGallery");

  async function loadFontGallery() {
    if (!fontGallery || !fontPathInput) return;
    fontGallery.innerHTML = "Loading fonts …";
    try {
      const response = await fetch("/api/fonts", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "Error");

      const fonts = data.fonts || [];
      if (!fonts.length) {
        fontGallery.innerHTML = "<p>No fonts available.</p>";
        return;
      }

      fontGallery.replaceChildren();
      fonts.forEach((font) => {
        const item = document.createElement("div");
        const selected = font.path === fontPathInput.value;
        item.className = `font-gallery-item${selected ? " current" : ""}`;
        item.tabIndex = 0;
        item.setAttribute("role", "button");
        item.setAttribute("aria-label", `Use font ${font.name || font.filename}`);

        const preview = document.createElement("img");
        preview.src = `${font.preview_url}?v=${encodeURIComponent(font.filename)}`;
        preview.alt = `Preview of ${font.name || font.filename}`;
        preview.loading = "lazy";

        const meta = document.createElement("div");
        meta.className = "font-gallery-meta";
        const name = document.createElement("strong");
        name.textContent = font.name || font.filename;
        const filename = document.createElement("span");
        filename.textContent = font.filename;
        meta.append(name, filename);

        const selectFont = () => {
          setSelectedFontPath(font.path);
          renderDisplayPreview();
          fontGallery.querySelectorAll(".font-gallery-item").forEach((entry) => entry.classList.remove("current"));
          item.classList.add("current");
          showToast(`Font selected: ${font.name || font.filename}`);
        };

        item.addEventListener("click", selectFont);
        item.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            selectFont();
          }
        });

        item.append(preview, meta);

        if (font.deletable) {
          const deleteButton = document.createElement("button");
          deleteButton.type = "button";
          deleteButton.className = "gallery-delete";
          deleteButton.textContent = "Delete";
          deleteButton.addEventListener("click", async (event) => {
            event.stopPropagation();
            if (!confirm(`Delete font "${font.filename}"?`)) return;

            const response = await fetch(`/api/font/${encodeURIComponent(font.filename)}`, { method: "DELETE" });
            const result = await response.json().catch(() => ({}));
            if (!response.ok || !result.ok) {
              showToast("Deletion failed: " + (result.error || "unknown error"), true);
              return;
            }
            await loadConfig();
            await loadFontGallery();
            showToast(`Deleted ${font.filename}.`);
          });
          item.appendChild(deleteButton);
        }
        fontGallery.appendChild(item);
      });
    } catch (error) {
      console.error(error);
      fontGallery.innerHTML = "<p>Error loading font gallery.</p>";
    }
  }

  openFontGallery?.addEventListener("click", async () => {
    if (!fontGallery) return;
    fontGallery.classList.toggle("hidden");
    openFontGallery.textContent = fontGallery.classList.contains("hidden")
      ? "Open font gallery"
      : "Close font gallery";
    if (!fontGallery.classList.contains("hidden")) await loadFontGallery();
  });

  fontUpload?.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      const response = await fetch("/api/font", { method: "POST", body: formData });
      const data = await response.json();
      if (!response.ok || !data.ok || !data.font_path) {
        throw new Error(data.error || "unknown error");
      }
      setSelectedFontPath(data.font_path);
      renderDisplayPreview();
      fontUpload.value = "";
      if (fontGallery && !fontGallery.classList.contains("hidden")) await loadFontGallery();
      showToast("Font uploaded and selected.");
    } catch (error) {
      console.error(error);
      showToast(`Font upload failed: ${error.message || "network error"}`, true);
    }
  });

  setupFallbackImageControl({
    kind: "normal",
    uploadId: "fallbackUpload",
    inputId: "fallbackImage",
    pathId: "fallbackImagePath",
    openId: "openFallbackGallery",
    galleryId: "fallbackGallery",
    label: "Fallback image",
  });
  setupFallbackImageControl({
    kind: "turn",
    uploadId: "sideFlipUpload",
    inputId: "sideFlipImage",
    pathId: "sideFlipImagePath",
    openId: "openSideFlipGallery",
    galleryId: "sideFlipGallery",
    label: "Turn-record image",
  });

  ["useDynamicBg", "useDynamicText"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", () => {
      syncAllManualColorStates();
      renderDisplayPreview();
    });
  });

  ["invertDynamicColors", "imageUppercase"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", () => renderDisplayPreview());
  });
  ["bgColor", "textColor"].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", () => renderDisplayPreview());
  });

  const reverseDisplayFields = Object.fromEntries(
    Object.entries(DISPLAY_LAYOUT_FIELDS).map(([key, id]) => [id, key]),
  );
  Object.values(DISPLAY_LAYOUT_FIELDS).forEach((id) => {
    const control = document.getElementById(id);
    if (!control) return;
    const eventName = control.type === "checkbox" ? "change" : "input";
    control.addEventListener(eventName, () => {
      syncDisplayDesigner({ changedKey: reverseDisplayFields[id], announce: true });
    });
  });

  document.querySelectorAll("[data-display-preset]").forEach((button) => {
    button.addEventListener("click", () => applyDisplayPreset(button.dataset.displayPreset));
  });
  loadDisplayPreviewTrack();
  [
    "adaptiveSampleEnabled",
    "fallbackEnabled",
    "sideFlipEnabled",
    "discoveryEnabled",
    "useHA",
    "debugLogs",
    "discogsEnabled",
  ].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", syncDependentSettingStates);
  });

  document.getElementById("discogsConnect")?.addEventListener("click", connectDiscogs);
  document.getElementById("discogsSync")?.addEventListener("click", startDiscogsSync);
  syncDependentSettingStates();
  loadDiscogsStatus();
});


async function loadConfig() {
    const r = await fetch("/api/config");
    const cfg = await r.json();
    CURRENT_CFG = cfg;

    const audio = cfg.audio || {};
    const image = cfg.image || {};
    const fallback = cfg.fallback || {};
    const divoom = cfg.divoom || {};
    const discovery = divoom.discovery || {};
    const debug = cfg.debug || {};
    const behavior = cfg.behavior || {};
    const shazam = cfg.shazam || {};
    const spotify = cfg.spotify || {};
    const discogs = cfg.discogs || {};
    const homeassistant = cfg.homeassistant || {};

    // AUDIO
    document.getElementById("audioDeviceName").value =
        audio.device_name_contains || "";
    document.getElementById("audioSampleSeconds").value =
        audio.sample_seconds ?? 4;
    document.getElementById("audioSampleRate").value =
        audio.sample_rate ?? 44100;
    document.getElementById("audioChannels").value =
        audio.channels ?? 1;
    const adaptiveSample = audio.adaptive_sample || {};
    const adaptiveDurations = Array.isArray(adaptiveSample.failure_durations_seconds)
        ? adaptiveSample.failure_durations_seconds
        : [6, 8];
    document.getElementById("adaptiveSampleEnabled").checked =
        !!adaptiveSample.enabled;
    document.getElementById("adaptiveSampleFirstFailure").value =
        adaptiveDurations[0] ?? 6;
    document.getElementById("adaptiveSampleLaterFailures").value =
        adaptiveDurations[1] ?? adaptiveDurations[0] ?? 8;
    syncAdaptiveSampleState();

    // IMAGE / DISPLAY
    document.getElementById("imageShowCover").checked = image.show_cover !== false;
    document.getElementById("imageShowArtist").checked = image.show_artist !== false;
    document.getElementById("imageShowTitle").checked = image.show_title !== false;
    document.getElementById("imageShowAlbum").checked = !!image.show_album;
    document.getElementById("imageTopMargin").value = image.top_margin ?? 1;
    document.getElementById("imageCoverSize").value = image.cover_size ?? 46;
    document.getElementById("imageMarginImageText").value = image.margin_image_text ?? 3;
    document.getElementById("imageLineSpacingMargin").value = image.line_spacing_margin ?? 3;
    setSelectedFontPath(image.font_path || "");
    document.getElementById("imageFontSize").value = image.font_size ?? 5;

    document.getElementById("textColor").value =
        rgbToHex(image.text_color || [255, 255, 255]);
    document.getElementById("bgColor").value =
        rgbToHex(image.manual_bg_color || [0, 0, 0]);

    document.getElementById("imageUppercase").checked =
        !!image.uppercase;
    document.getElementById("useDynamicBg").checked =
        !!image.use_dynamic_bg;
    document.getElementById("useDynamicText").checked =
        !!image.use_dynamic_text_color;
    document.getElementById("invertDynamicColors").checked =
        !!image.invert_dynamic_colors;
    syncAllManualColorStates();

    document.getElementById("marqueeSpeed").value =
        image.marquee_speed ?? 20;
    syncDisplayDesigner();

    // FALLBACK
    document.getElementById("fallbackEnabled").checked =
        !!fallback.enabled;
    document.getElementById("sideFlipEnabled").checked =
        fallback.side_flip_enabled !== false;
    setSelectedImagePath(
        "fallbackImage",
        "fallbackImagePath",
        fallback.image_path || "",
    );
    setSelectedImagePath(
        "sideFlipImage",
        "sideFlipImagePath",
        fallback.side_flip_image_path || "assets/fallback/turn_record.png",
    );
    document.getElementById("fallbackAllowedFailures").value =
        fallback.allowed_failures ?? 3;

    // DIVOOM / PIXOO
    document.getElementById("divoomIp").value =
        divoom.ip || "";
    document.getElementById("divoomDeviceName").value =
        divoom.device_name || "";
    document.getElementById("divoomDeviceID").value = 
        divoom.device_id || "";
    document.getElementById("divoomDeviceMAC").value = 
        divoom.device_mac || "";
    document.getElementById("divoomTimeout").value =
        divoom.timeout ?? 2.0;
    document.getElementById("divoomAutoResetGif").checked =
        !!divoom.auto_reset_gif_id;

    document.getElementById("discoveryEnabled").checked =
        !!discovery.enabled;
    document.getElementById("subnetPrefix").value =
        discovery.subnet_prefix || "";
    document.getElementById("ipRangeStart").value =
        discovery.ip_range_start ?? 100;
    document.getElementById("ipRangeEnd").value =
        discovery.ip_range_end ?? 199;

    // DISCOGS
    document.getElementById("discogsEnabled").checked = !!discogs.enabled;
    document.getElementById("discogsPreferCollection").checked = discogs.prefer_collection !== false;
    document.getElementById("discogsSequenceMatching").checked = discogs.sequence_matching !== false;
    document.getElementById("discogsInferNext").checked = discogs.infer_unrecognized_next !== false;
    document.getElementById("discogsVinylOnly").checked = discogs.vinyl_only !== false;
    document.getElementById("discogsMinConfidence").value = discogs.min_match_confidence ?? 0.72;

    // SPOTIFY
    document.getElementById("spotifyPollSeconds").value =
        spotify.poll_seconds ?? 2;

    // BEHAVIOR
    document.getElementById("behaviorLoopDelay").value =
        behavior.loop_delay_seconds ?? 1;
    document.getElementById("behaviorAutoSleep").value =
        behavior.auto_sleep ?? 50;
    document.getElementById("shazamTimeout").value =
        shazam.timeout_seconds ?? 15;

    // DEBUG
    document.getElementById("debugLogs").checked =
        !!debug.logs;
    document.getElementById("debugPixooFramePath").value =
        debug.pixoo_frame_path || "";
    document.getElementById("debugPreviewPath").value =
        debug.preview_path || "";
    document.getElementById("debugWavPath").value =
        debug.wav_path || "";

    // HOME ASSISTANT
    document.getElementById("useHA").checked =
        !!homeassistant.use_ha;
    document.getElementById("baseURL").value =
        homeassistant.base_url || "";
    document.getElementById("webHookID").value =
        homeassistant.webhook_id || "";

    syncDependentSettingStates();
}

document.getElementById("settings-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!CURRENT_CFG) return;

    const cfg = JSON.parse(JSON.stringify(CURRENT_CFG));

    cfg.audio = cfg.audio || {};
    cfg.audio.adaptive_sample = cfg.audio.adaptive_sample || {};
    cfg.image = cfg.image || {};
    cfg.fallback = cfg.fallback || {};
    cfg.divoom = cfg.divoom || {};
    cfg.divoom.discovery = cfg.divoom.discovery || {};
    cfg.debug = cfg.debug || {};
    cfg.behavior = cfg.behavior || {};
    cfg.shazam = cfg.shazam || {};
    cfg.spotify = cfg.spotify || {};
    cfg.discogs = cfg.discogs || {};
    cfg.homeassistant = cfg.homeassistant || {};

    const audio = cfg.audio;
    const adaptiveSample = cfg.audio.adaptive_sample;
    const image = cfg.image;
    const fallback = cfg.fallback;
    const divoom = cfg.divoom;
    const discovery = cfg.divoom.discovery;
    const debug = cfg.debug;
    const behavior = cfg.behavior;
    const shazam = cfg.shazam;
    const spotify = cfg.spotify;
    const discogs = cfg.discogs;
    const homeassistant = cfg.homeassistant;

    // AUDIO
    audio.device_name_contains =
        document.getElementById("audioDeviceName").value;
    audio.sample_seconds =
        parseFloat(document.getElementById("audioSampleSeconds").value) || 4;
    audio.sample_rate =
        parseInt(document.getElementById("audioSampleRate").value) || 44100;
    audio.channels =
        parseInt(document.getElementById("audioChannels").value) || 1;
    adaptiveSample.enabled =
        document.getElementById("adaptiveSampleEnabled").checked;
    adaptiveSample.failure_durations_seconds = [
        Math.max(0.5, parseFloat(document.getElementById("adaptiveSampleFirstFailure").value) || 6),
        Math.max(0.5, parseFloat(document.getElementById("adaptiveSampleLaterFailures").value) || 8),
    ];

    // IMAGE / DISPLAY
    const fittedDisplay = syncDisplayDesigner();
    image.canvas_size = 64;
    image.show_cover = fittedDisplay.showCover;
    image.show_artist = fittedDisplay.showArtist;
    image.show_title = fittedDisplay.showTitle;
    image.show_album = fittedDisplay.showAlbum;
    image.top_margin = fittedDisplay.topMargin;
    image.cover_size = fittedDisplay.coverSize;
    image.margin_image_text = fittedDisplay.coverGap;
    image.line_spacing_margin = fittedDisplay.lineGap;
    image.font_path = document.getElementById("imageFontPath").value;
    image.font_size = fittedDisplay.fontSize;

    image.text_color =
        hexToRgb(document.getElementById("textColor").value);
    image.manual_bg_color =
        hexToRgb(document.getElementById("bgColor").value);

    image.uppercase =
        document.getElementById("imageUppercase").checked;
    image.use_dynamic_bg =
        document.getElementById("useDynamicBg").checked;
    image.use_dynamic_text_color =
        document.getElementById("useDynamicText").checked;
    image.invert_dynamic_colors =
        document.getElementById("invertDynamicColors").checked;

    image.marquee_speed =
        parseInt(document.getElementById("marqueeSpeed").value) || 20;

    // FALLBACK
    fallback.enabled =
        document.getElementById("fallbackEnabled").checked;
    fallback.image_path =
        document.getElementById("fallbackImage").value;
    fallback.side_flip_enabled =
        document.getElementById("sideFlipEnabled").checked;
    fallback.side_flip_image_path =
        document.getElementById("sideFlipImage").value || "assets/fallback/turn_record.png";
    fallback.allowed_failures = Math.max(
        1,
        parseInt(document.getElementById("fallbackAllowedFailures").value, 10) || 3,
    );

    // DIVOOM
    divoom.ip =
        document.getElementById("divoomIp").value;
    divoom.device_name =
        document.getElementById("divoomDeviceName").value;
    divoom.device_id =
        parseInt(document.getElementById("divoomDeviceID").value) || 0;
    divoom.device_mac =
        document.getElementById("divoomDeviceMAC").value;
    divoom.timeout =
        parseFloat(document.getElementById("divoomTimeout").value) || 2.0;
    divoom.auto_reset_gif_id =
        document.getElementById("divoomAutoResetGif").checked;

    // DISCOVERY
    discovery.enabled =
        document.getElementById("discoveryEnabled").checked;
    discovery.subnet_prefix =
        document.getElementById("subnetPrefix").value;
    discovery.ip_range_start =
        parseInt(document.getElementById("ipRangeStart").value) || 100;
    discovery.ip_range_end =
        parseInt(document.getElementById("ipRangeEnd").value) || 199;

    // DISCOGS
    discogs.enabled = document.getElementById("discogsEnabled").checked;
    discogs.prefer_collection = document.getElementById("discogsPreferCollection").checked;
    discogs.sequence_matching = document.getElementById("discogsSequenceMatching").checked;
    discogs.infer_unrecognized_next = document.getElementById("discogsInferNext").checked;
    discogs.vinyl_only = document.getElementById("discogsVinylOnly").checked;
    discogs.min_match_confidence = Math.min(
        0.95,
        Math.max(0.5, parseFloat(document.getElementById("discogsMinConfidence").value) || 0.72),
    );

    // SPOTIFY
    spotify.poll_seconds = Math.min(
        60,
        Math.max(1, parseFloat(document.getElementById("spotifyPollSeconds").value) || 2),
    );

    // BEHAVIOR
    behavior.loop_delay_seconds =
        parseFloat(document.getElementById("behaviorLoopDelay").value) || 1;
    behavior.auto_sleep =
        Math.max(0, parseInt(document.getElementById("behaviorAutoSleep").value, 10) || 0);
    shazam.timeout_seconds = Math.min(
        60,
        Math.max(5, parseFloat(document.getElementById("shazamTimeout").value) || 15),
    );

    // DEBUG
    debug.logs =
        document.getElementById("debugLogs").checked;
    debug.pixoo_frame_path =
        document.getElementById("debugPixooFramePath").value;
    debug.preview_path =
        document.getElementById("debugPreviewPath").value;
    debug.wav_path =
        document.getElementById("debugWavPath").value;

    // HOME ASSISTANT
    homeassistant.use_ha =
        document.getElementById("useHA").checked;
    homeassistant.base_url =
        document.getElementById("baseURL").value;
    homeassistant.webhook_id =
        document.getElementById("webHookID").value;

    try {
        const response = await fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(cfg),
        });
        if (!response.ok) throw new Error(`Save failed: ${response.status}`);
        const result = await response.json();
        CURRENT_CFG = cfg;
        showToast(result.display_refresh_requested
            ? "Settings saved. Pixoo display refresh requested."
            : "Settings saved.");
    } catch (error) {
        console.error(error);
        showToast("Settings could not be saved.", true);
    }
});

loadConfig().catch((error) => {
    console.error(error);
    showToast("Configuration could not be loaded.", true);
});

const resetBtn = document.getElementById("reset-defaults");
if (resetBtn) {
    resetBtn.addEventListener("click", async () => {
        if (!confirm("Reset all settings to defaults?")) return;

        const res = await fetch("/api/config/reset", {
            method: "POST",
        });

        const data = await res.json().catch(() => ({}));
        if (data.ok) {
            await loadConfig();
            showToast("Settings reset to defaults.");
        } else {
            showToast("Reset failed.", true);
        }
    });
}

// Minimal UI accordion behavior
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".settings-card-header").forEach((btn) => {
        btn.addEventListener("click", () => {
            const card = btn.closest(".settings-card");
            if (!card) return;
            const isOpen = card.classList.toggle("is-open");
            btn.setAttribute("aria-expanded", String(isOpen));
        });
    });
});


// Mobile settings use a category-first view instead of one long page.
document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("settings-form");
    const detailHeader = form?.querySelector(".mobile-settings-detail-header");
    const currentLabel = form?.querySelector(".mobile-settings-current");
    const backButton = form?.querySelector(".mobile-settings-back");
    const categoryButtons = form?.querySelectorAll("[data-settings-target]") || [];

    if (!form || !detailHeader || !backButton) return;

    const openCategory = (targetId, label) => {
        const target = document.getElementById(targetId);
        if (!target) return;

        form.querySelectorAll(".settings-card.mobile-selected-category").forEach((card) => {
            card.classList.remove("mobile-selected-category");
        });
        target.classList.add("mobile-selected-category", "is-open");
        target.querySelector(".settings-card-header")?.setAttribute("aria-expanded", "true");
        form.classList.add("mobile-category-open");
        detailHeader.hidden = false;
        if (currentLabel) currentLabel.textContent = label || "Settings";
        window.scrollTo({ top: 0, behavior: "smooth" });
    };

    const closeCategory = () => {
        form.classList.remove("mobile-category-open");
        detailHeader.hidden = true;
        form.querySelectorAll(".settings-card.mobile-selected-category").forEach((card) => {
            card.classList.remove("mobile-selected-category");
        });
        window.scrollTo({ top: 0, behavior: "smooth" });
    };

    categoryButtons.forEach((button) => {
        button.addEventListener("click", () => {
            openCategory(
                button.dataset.settingsTarget,
                button.querySelector("strong")?.textContent?.trim(),
            );
        });
    });

    backButton.addEventListener("click", closeCategory);

    const hashTarget = window.location.hash.replace("#", "");
    if (window.matchMedia("(max-width: 760px)").matches && hashTarget) {
        const matchingButton = [...categoryButtons].find(
            (button) => button.dataset.settingsTarget === hashTarget,
        );
        if (matchingButton) {
            openCategory(hashTarget, matchingButton.querySelector("strong")?.textContent?.trim());
        }
    }
});
