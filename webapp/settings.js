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


document.addEventListener("DOMContentLoaded", () => {
  const fallbackUploadInput = document.getElementById("fallbackUpload");
  const fallbackPathInput = document.getElementById("fallbackImage");
  const openGalleryBtn = document.getElementById("openFallbackGallery");
  const galleryContainer = document.getElementById("fallbackGallery");

  if (fallbackUploadInput) {
    fallbackUploadInput.addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;

      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch("/api/fallback-image", {
          method: "POST",
          body: formData,
        });
        const data = await res.json();
        if (data.ok && data.image_path) {
          fallbackPathInput.value = data.image_path;
          alert("Fallback image updated.");
          if (!galleryContainer.classList.contains("hidden")) {
            await loadFallbackGallery();
          }
        } else {
          alert("Upload failed: " + (data.error || "unknown error"));
        }
      } catch (err) {
        console.error(err);
        alert("Upload failed (network error).");
      }
    });
  }

  async function loadFallbackGallery() {
    galleryContainer.innerHTML = "Loading images …";
    try {
      const res = await fetch("/api/fallback-images");
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Error");

      const images = data.images || [];
      if (!images.length) {
        galleryContainer.innerHTML = "<p>No uploaded fallback images available.</p>";
        return;
      }

      galleryContainer.innerHTML = "";
      images.forEach(img => {
        const item = document.createElement("div");
        item.className = "gallery-item" + (img.is_current ? " current" : "");

        const thumbnail = document.createElement("img");
        thumbnail.src = img.url;
        thumbnail.alt = img.filename;

        const name = document.createElement("div");
        name.textContent = img.filename;

        const selectBtn = document.createElement("button");
        selectBtn.type = "button";
        selectBtn.textContent = "Use";
        selectBtn.addEventListener("click", () => {
          fallbackPathInput.value = img.path; 
          document.querySelectorAll(".gallery-item").forEach(el => el.classList.remove("current"));
          item.classList.add("current");
        });

        const deleteBtn = document.createElement("button");
        deleteBtn.type = "button";
        deleteBtn.textContent = "Delete";
        deleteBtn.addEventListener("click", async () => {
          if (!confirm(`"${img.filename}" really delete?`)) return;
          const res = await fetch(`/api/fallback-image/${encodeURIComponent(img.filename)}`, {
            method: "DELETE",
          });
          const out = await res.json();
          if (!out.ok) {
            alert("Deletion failed: " + (out.error || "unknown error"));
          } else {
            await loadFallbackGallery();
          }
        });

        item.appendChild(thumbnail);
        item.appendChild(name);
        item.appendChild(selectBtn);
        item.appendChild(deleteBtn);
        galleryContainer.appendChild(item);
      });
    } catch (err) {
      console.error(err);
      galleryContainer.innerHTML = "<p>Error loading gallery.</p>";
    }
  }

  if (openGalleryBtn && galleryContainer) {
    openGalleryBtn.addEventListener("click", async () => {
      galleryContainer.classList.toggle("hidden");
      if (!galleryContainer.classList.contains("hidden")) {
        await loadFallbackGallery();
      }
    });
  }
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
    document.getElementById("audioOutputWav").value =
        audio.output_wav || "";

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

    document.getElementById("imagePreviewScale").value =
        image.preview_scale ?? 8;
    document.getElementById("marqueeSpeed").value =
        image.marquee_speed ?? 20;
    document.getElementById("imageSleepSeconds").value =
        image.sleep_seconds ?? 0.01;

    // FALLBACK
    document.getElementById("fallbackEnabled").checked =
        !!fallback.enabled;
    document.getElementById("fallbackImage").value =
        fallback.image_path || "";
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

    // BEHAVIOR
    document.getElementById("behaviorLoopDelay").value =
        behavior.loop_delay_seconds ?? 1;
    document.getElementById("behaviorAutoSleep").value =
        behavior.auto_sleep ?? 50;

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
}

document.getElementById("settings-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!CURRENT_CFG) return;

    const cfg = CURRENT_CFG;

    cfg.audio = cfg.audio || {};
    cfg.image = cfg.image || {};
    cfg.fallback = cfg.fallback || {};
    cfg.divoom = cfg.divoom || {};
    cfg.divoom.discovery = cfg.divoom.discovery || {};
    cfg.debug = cfg.debug || {};
    cfg.behavior = cfg.behavior || {};
    cfg.homeassistant = cfg.homeassistant || {};

    const audio = cfg.audio;
    const image = cfg.image;
    const fallback = cfg.fallback;
    const divoom = cfg.divoom;
    const discovery = cfg.divoom.discovery;
    const debug = cfg.debug;
    const behavior = cfg.behavior;
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
    audio.output_wav =
        document.getElementById("audioOutputWav").value;

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
    fallback.allowed_failures =
        parseInt(document.getElementById("fallbackAllowedFailures").value) || 3;

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

    // BEHAVIOR
    behavior.loop_delay_seconds =
        parseFloat(document.getElementById("behaviorLoopDelay").value) || 1;
    behavior.auto_sleep =
        parseInt(document.getElementById("behaviorAutoSleep").value) || 50;

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

    await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg),
    });

    alert("Saved settings.");
    
});

loadConfig();

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
            alert("Settings reset to defaults.");
        } else {
            alert("Reset failed.");
        }
    });
}
