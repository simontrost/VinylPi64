// pixoo.js

async function fetchJson(url, options) {
    const res = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        const msg = data && data.error ? data.error : res.statusText;
        throw new Error(msg || "Request failed");
    }
    return data;
}

async function loadPixooState() {
    const statusEl = document.getElementById("pixoo-status-text");
    const subEl = document.getElementById("pixoo-status-sub");
    const slider = document.getElementById("pixooBrightness");
    const sliderVal = document.getElementById("pixooBrightnessValue");
    const channelButtons = document.querySelectorAll(".pixoo-channel-btn");

    statusEl.textContent = "Loading Pixoo status...";

    try {
        const data = await fetchJson("/api/pixoo/state");

        if (!data.ok || !data.reachable) {
            statusEl.textContent = "Pixoo not reachable.";
            subEl.textContent = data.error || "";
            slider.disabled = true;
            channelButtons.forEach(b => b.disabled = true);
            return;
        }

        statusEl.textContent = "Pixoo is online.";
        subEl.textContent = `Brightness: ${data.brightness ?? "?"}, Channel: ${data.channel ?? "?"}`;

        if (typeof data.brightness === "number") {
            slider.value = data.brightness;
            sliderVal.textContent = `${data.brightness}%`;
        } else {
            sliderVal.textContent = "–%";
        }

        if (typeof data.channel === "number") {
            channelButtons.forEach(btn => {
                const ch = parseInt(btn.dataset.channel, 10);
                btn.classList.toggle("active", ch === data.channel);
            });
        }

    } catch (err) {
        statusEl.textContent = "Error loading Pixoo status.";
        subEl.textContent = String(err);
    }
}

function setupBrightness() {
    const slider = document.getElementById("pixooBrightness");
    const sliderVal = document.getElementById("pixooBrightnessValue");
    if (!slider) return;

    let debounceTimer = null;

    slider.addEventListener("input", () => {
        sliderVal.textContent = `${slider.value}%`;
    });

    slider.addEventListener("change", () => {
        if (debounceTimer) {
            clearTimeout(debounceTimer);
        }
        debounceTimer = setTimeout(async () => {
            try {
                await fetchJson("/api/pixoo/brightness", {
                    method: "POST",
                    body: JSON.stringify({ brightness: parseInt(slider.value, 10) }),
                });
            } catch (err) {
                console.error("Error setting brightness:", err);
            }
        }, 150);
    });
}

function setupChannels() {
    const buttons = document.querySelectorAll(".pixoo-channel-btn");
    buttons.forEach(btn => {
        btn.addEventListener("click", async () => {
            const channel = parseInt(btn.dataset.channel, 10);
            buttons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            try {
                await fetchJson("/api/pixoo/channel", {
                    method: "POST",
                    body: JSON.stringify({ channel }),
                });
            } catch (err) {
                console.error("Error setting channel:", err);
            }
        });
    });
}

function setupReboot() {
    const btn = document.getElementById("pixooRebootBtn");
    const label = document.getElementById("pixooRebootStatus");
    if (!btn) return;

    btn.addEventListener("click", async () => {
        label.textContent = "Rebooting...";
        btn.disabled = true;
        try {
            await fetchJson("/api/pixoo/reboot", { method: "POST" });
            label.textContent = "Pixoo reboot command sent.";
        } catch (err) {
            label.textContent = "Error sending reboot.";
            console.error(err);
        } finally {
            setTimeout(() => {
                btn.disabled = false;
                label.textContent = "";
                loadPixooState();
            }, 4000);
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    setupBrightness();
    setupChannels();
    setupReboot();
    loadPixooState();
});
