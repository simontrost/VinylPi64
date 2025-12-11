document.addEventListener("DOMContentLoaded", () => {
    const statusText = document.getElementById("pixoo-status-text");
    const statusSub  = document.getElementById("pixoo-status-sub");
    const discoverBtn    = document.getElementById("pixooDiscoverBtn");
    const discoverStatus = document.getElementById("pixooDiscoverStatus");


    const brightnessSlider = document.getElementById("pixooBrightness");
    const brightnessValue  = document.getElementById("pixooBrightnessValue");

    const channelButtons = Array.from(
        document.querySelectorAll(".pixoo-channel-btn")
    );

    const rebootBtn     = document.getElementById("pixooRebootBtn");
    const rebootStatus  = document.getElementById("pixooRebootStatus");

    const fetchLikesBtn = document.getElementById("pixooFetchLikesBtn");
    const likesStatus   = document.getElementById("pixooLikesStatus");
    const likesSelect   = document.getElementById("pixooLikesSelect");
    const playLikeBtn   = document.getElementById("pixooPlayLikeBtn");

    let brightnessDebounce = null;

    function setStatus(text, sub = "") {
        if (statusText) statusText.textContent = text;
        if (statusSub)  statusSub.textContent  = sub;
    }

    function setBrightnessUI(value) {
        if (!brightnessSlider || !brightnessValue) return;
        brightnessSlider.value = value;
        brightnessValue.textContent = value + "%";
    }

    function setActiveChannel(channelIndex) {
        channelButtons.forEach(btn => {
            if (parseInt(btn.dataset.channel, 10) === channelIndex) {
                btn.classList.add("active");
            } else {
                btn.classList.remove("active");
            }
        });
    }

    async function loadPixooStatus() {
        try {
            const res = await fetch("/api/pixoo/status");
            const data = await res.json();

            if (!data.ok || !data.online) {
                setStatus("Pixoo not reachable.", data.error || "");
                return;
            }

            const brightness = typeof data.brightness === "number"
                ? data.brightness
                : 50;

            const channel = typeof data.channel === "number"
                ? data.channel
                : 3;

            setStatus(
                `Connected to ${data.device_name || "Pixoo"}`,
                `Brightness: ${brightness}% – Channel: ${channel}`
            );
            setBrightnessUI(brightness);
            setActiveChannel(channel);
        } catch (err) {
            console.error("Error loading Pixoo status:", err);
            setStatus("Error loading Pixoo status.", String(err));
        }
    }

    async function discoverDeviceAndSave() {
        if (!discoverStatus) return;

        discoverStatus.textContent = "Searching device via Divoom cloud...";

        try {
            const res = await fetch("/api/pixoo/discover-and-save", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            });
            const data = await res.json();

            if (!data.ok) {
                throw new Error(data.error || "Unknown error");
            }

            const dev = data.device || {};
            const ip  = dev.device_private_ip || "unknown IP";
            const id  = dev.device_id != null ? dev.device_id : "?";

            discoverStatus.textContent =
                `Found ${dev.device_name || "Pixoo"} at ${ip} (DeviceId ${id}) and saved to config.`;

            if (typeof loadPixooStatus === "function") {
                loadPixooStatus();
            }
        } catch (err) {
            console.error("Error during discovery:", err);
            discoverStatus.textContent = "Error: " + err.message;
        }
    }


    async function sendBrightness(value) {
        try {
            const res = await fetch("/api/pixoo/brightness", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ brightness: value }),
            });
            const data = await res.json();
            if (!data.ok) {
                throw new Error(data.error || "Unknown error");
            }
            setStatus("Pixoo connected", `Brightness set to ${value}%`);
        } catch (err) {
            console.error("Error setting brightness:", err);
            setStatus("Error setting brightness.", String(err));
        }
    }

    async function sendChannel(channelIndex) {
        try {
            const res = await fetch("/api/pixoo/channel", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ channel: channelIndex }),
            });
            const data = await res.json();
            if (!data.ok) {
                throw new Error(data.error || "Unknown error");
            }
            setActiveChannel(channelIndex);
            setStatus("Pixoo connected", `Channel switched to ${channelIndex}`);
        } catch (err) {
            console.error("Error setting channel:", err);
            setStatus("Error setting channel.", String(err));
        }
    }

    async function rebootPixoo() {
        if (!rebootBtn || !rebootStatus) return;

        rebootStatus.textContent = "Rebooting...";
        rebootBtn.disabled = true;

        try {
            const res = await fetch("/api/pixoo/reboot", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            });
            const data = await res.json();
            if (!data.ok) {
                throw new Error(data.error || "Unknown error");
            }
            rebootStatus.textContent = "Reboot command sent.";
        } catch (err) {
            console.error("Error rebooting Pixoo:", err);
            rebootStatus.textContent = "Error while rebooting.";
        } finally {
            setTimeout(() => {
                rebootBtn.disabled = false;
            }, 3000);
        }
    }

    // --- NEW: Community GIFs ---

    async function loadLikedGifs() {
        if (!likesStatus || !likesSelect) return;

        likesStatus.textContent = "Loading liked GIFs...";
        likesSelect.innerHTML = `<option value="">Loading…</option>`;

        try {
            const res = await fetch("/api/pixoo/liked-gifs");
            const data = await res.json();

            if (!data.ok) {
                throw new Error(data.error || "Unknown error");
            }

            const gifs = data.gifs || [];

            if (gifs.length === 0) {
                likesSelect.innerHTML =
                    `<option value="">No liked GIFs found</option>`;
                likesStatus.textContent = "No liked GIFs found.";
                return;
            }

            likesSelect.innerHTML = "";
            gifs.forEach(gif => {
                const opt = document.createElement("option");
                opt.value = gif.file_id;
                opt.textContent = gif.file_name || gif.file_id;
                likesSelect.appendChild(opt);
            });

            likesStatus.textContent = `Loaded ${gifs.length} GIF(s).`;
        } catch (err) {
            console.error("Error loading liked GIFs:", err);
            likesSelect.innerHTML =
                `<option value="">Error loading liked GIFs</option>`;
            likesStatus.textContent = "Error loading liked GIFs.";
        }
    }

    async function playSelectedLikedGif() {
        if (!likesSelect || !likesStatus) return;

        const fileId = likesSelect.value;
        if (!fileId) {
            likesStatus.textContent = "Please select a GIF first.";
            return;
        }

        likesStatus.textContent = "Sending GIF to Pixoo...";

        try {
            const res = await fetch("/api/pixoo/play-remote", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ file_id: fileId }),
            });
            const data = await res.json();

            if (!data.ok) {
                throw new Error(data.error || "Unknown error");
            }

            likesStatus.textContent = "GIF should now be playing on Pixoo.";
        } catch (err) {
            console.error("Error playing remote GIF:", err);
            likesStatus.textContent = "Error while sending GIF.";
        }
    }

    // --- Event-Wiring ---

    if (brightnessSlider) {
        brightnessSlider.addEventListener("input", (e) => {
            const value = parseInt(e.target.value, 10);
            setBrightnessUI(value);

            if (brightnessDebounce) {
                clearTimeout(brightnessDebounce);
            }
            brightnessDebounce = setTimeout(() => {
                sendBrightness(value);
            }, 150);
        });
    }

    if (discoverBtn) {
        discoverBtn.addEventListener("click", () => {
            discoverDeviceAndSave();
        });
    }

    channelButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const ch = parseInt(btn.dataset.channel, 10);
            sendChannel(ch);
        });
    });

    if (rebootBtn) {
        rebootBtn.addEventListener("click", () => {
            if (confirm("Really reboot Pixoo?")) {
                rebootPixoo();
            }
        });
    }

    if (fetchLikesBtn) {
        fetchLikesBtn.addEventListener("click", () => {
            loadLikedGifs();
        });
    }

    if (playLikeBtn) {
        playLikeBtn.addEventListener("click", () => {
            playSelectedLikedGif();
        });
    }

    loadPixooStatus();
});
