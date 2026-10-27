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
        const normalized = Math.max(0, Math.min(100, Number(value) || 0));
        brightnessSlider.value = normalized;
        brightnessSlider.style.setProperty("--range-value", `${normalized}%`);
        brightnessValue.textContent = normalized + "%";
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

            // Discovery saves device details, but GIFs are loaded only on request.
            await loadPixooStatus();
            if (likesStatus) likesStatus.textContent = "Click Load liked GIFs to browse your Divoom likes.";
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

    async function loadLikedGifs(refresh = false) {
        if (!likesStatus || !likesSelect) return;

        likesStatus.textContent = "Loading liked GIFs...";
        const previousSelection = likesSelect.value;

        try {
            const res = await fetch(`/api/pixoo/liked-gifs${refresh ? "?refresh=1" : ""}`);
            const data = await res.json();

            if (!res.ok || !data.ok) {
                throw new Error(data.error || "Could not load liked GIFs");
            }
            if (data.needs_setup) {
                const saved = String(data.selected_file_id || "");
                likesSelect.replaceChildren(new Option("No GIF selected", ""));
                if (saved) likesSelect.add(new Option(`Saved GIF (${saved})`, saved));
                likesSelect.value = saved;
                likesStatus.textContent = "Configure your Pixoo in Settings to browse community GIFs.";
                return;
            }

            const gifs = data.gifs || [];

            if (gifs.length === 0) {
                likesSelect.replaceChildren(new Option("No liked GIFs found", ""));
                const remembered = String(data.selected_file_id || "");
                if (remembered) likesSelect.add(new Option(`Saved GIF (${remembered})`, remembered));
                likesSelect.value = remembered;
                likesStatus.textContent = "No liked GIFs found in the catalog.";
                return;
            }

            likesSelect.replaceChildren(new Option("Select a GIF", ""));
            gifs.forEach(gif => {
                const opt = document.createElement("option");
                opt.value = gif.file_id;
                opt.textContent = gif.file_name || gif.file_id;
                likesSelect.appendChild(opt);
            });

            const remembered = String(data.selected_file_id || "");
            if (remembered && !Array.from(likesSelect.options).some(o => o.value === remembered)) {
                likesSelect.add(new Option(`Saved GIF (${remembered})`, remembered));
            }
            likesSelect.value = remembered;
            likesStatus.textContent = `${gifs.length} liked GIF(s) ${data.cached ? "from cache" : "loaded"}.`;
        } catch (err) {
            console.error("Error loading liked GIFs:", err);
            // Retain the current selection if a network request fails.
            likesSelect.value = previousSelection;
            likesStatus.textContent = "Could not load liked GIFs. Your selection is unchanged.";
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
            loadLikedGifs(true);
        });
    }

    if (playLikeBtn) {
        playLikeBtn.addEventListener("click", () => {
            playSelectedLikedGif();
        });
    }

    likesSelect?.addEventListener("change", async () => {
        try {
            const response = await fetch("/api/pixoo/selected-gif", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ file_id: likesSelect.value }),
            });
            if (!response.ok) throw new Error("Save failed");
            likesStatus.textContent = "Selected GIF saved for this device.";
        } catch (error) {
            console.error(error);
            likesStatus.textContent = "Could not save GIF selection.";
        }
    });

    loadPixooStatus();
});
