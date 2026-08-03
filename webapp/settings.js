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
    document.getElementById(id)?.addEventListener("change", syncAllManualColorStates);
  });
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
    document.getElementById("imageCanvasSize").value =
        image.canvas_size ?? 64;
    document.getElementById("imageTopMargin").value =
        image.top_margin ?? 1;
    document.getElementById("imageCoverSize").value =
        image.cover_size ?? 46;
    document.getElementById("imageMarginImageText").value =
        image.margin_image_text ?? 3;
    document.getElementById("imageLineSpacingMargin").value =
        image.line_spacing_margin ?? 3;
    document.getElementById("imageFontPath").value =
        image.font_path || "";
    document.getElementById("imageFontSize").value =
        image.font_size ?? 5;

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

    document.getElementById("imagePreviewScale").value =
        image.preview_scale ?? 8;
    document.getElementById("marqueeSpeed").value =
        image.marquee_speed ?? 20;
    document.getElementById("imageSleepSeconds").value =
        image.sleep_seconds ?? 0.01;

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
    image.canvas_size =
        parseInt(document.getElementById("imageCanvasSize").value) || 64;
    image.top_margin =
        parseInt(document.getElementById("imageTopMargin").value) || 1;
    image.cover_size =
        parseInt(document.getElementById("imageCoverSize").value) || 46;
    image.margin_image_text =
        parseInt(document.getElementById("imageMarginImageText").value) || 3;
    image.line_spacing_margin =
        parseInt(document.getElementById("imageLineSpacingMargin").value) || 3;
    image.font_path =
        document.getElementById("imageFontPath").value;
    image.font_size =
        parseInt(document.getElementById("imageFontSize").value) || 5;

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

    image.preview_scale =
        parseInt(document.getElementById("imagePreviewScale").value) || 8;
    image.marquee_speed =
        parseInt(document.getElementById("marqueeSpeed").value) || 20;
    image.sleep_seconds =
        parseFloat(document.getElementById("imageSleepSeconds").value) || 0.01;

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

