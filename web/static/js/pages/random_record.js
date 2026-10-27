/* Suggest a record from one folder in the shared synced Discogs collection. */
(() => {
    const trigger = document.getElementById("random-record-button");
    const dialog = document.getElementById("random-record-dialog");
    if (!trigger || !dialog) return;

    const close = document.getElementById("random-record-close");
    const reroll = document.getElementById("random-record-reroll");
    const folderSelect = document.getElementById("random-record-folder-select");
    const result = document.getElementById("random-record-result");
    const message = document.getElementById("random-record-message");
    const settings = document.getElementById("random-record-settings");
    const cover = document.getElementById("random-record-cover");
    const placeholder = document.getElementById("random-record-placeholder");
    const coverStatus = document.getElementById("random-record-cover-status");
    const title = document.getElementById("random-record-title");
    const artist = document.getElementById("random-record-artist");
    let previousId = null;
    let request = null;
    let folderRequest = null;

    cover.addEventListener("load", () => {
        if (!cover.getAttribute("src")) return;
        cover.classList.remove("hidden");
        placeholder.classList.add("hidden");
    });
    cover.addEventListener("error", () => {
        cover.classList.add("hidden");
        placeholder.classList.remove("hidden");
        coverStatus.textContent = "Cover unavailable";
    });

    function updateSource(mode) {
        trigger.disabled = mode === "spotify";
        trigger.title = trigger.disabled ? "Available in Vinyl or Off mode" : "Suggest a record";
        if (trigger.disabled && dialog.open) dialog.close();
    }
    document.addEventListener("vinylpi:source-change", (event) => updateSource(event.detail.mode));

    async function loadFolders() {
        folderRequest?.abort();
        const controller = new AbortController();
        folderRequest = controller;
        try {
            const response = await fetch("/api/discogs/folders", {
                cache: "no-store", signal: controller.signal,
            });
            const data = await response.json();
            if (controller.signal.aborted || folderRequest !== controller || !dialog.open) return;
            if (!response.ok || !data.ok || !Array.isArray(data.folders)) {
                throw new Error(data.error || "Could not load collection folders.");
            }

            // Build options as plain text, never HTML from Discogs metadata.
            // Keep the user's current selection whenever it still exists.
            const selected = folderSelect.value;
            const options = data.folders.map((folder) => {
                const option = document.createElement("option");
                option.value = String(folder.id);
                option.textContent = `${folder.name} (${Number(folder.count) || 0})`;
                return option;
            });
            folderSelect.replaceChildren(...options);
            folderSelect.value = [...folderSelect.options].some((option) => option.value === selected)
                ? selected : "0";
            if (selected !== folderSelect.value) {
                previousId = null;
                request?.abort();
                request = null;
                pickRecord();
            }
        } catch (error) {
            if (!controller.signal.aborted) {
                console.warn("Discogs folder list unavailable; using current selection.", error);
            }
        } finally {
            if (folderRequest === controller) folderRequest = null;
        }
    }

    async function pickRecord() {
        if (request || trigger.disabled || !dialog.open) return;
        const controller = new AbortController();
        request = controller;
        reroll.disabled = true;
        reroll.textContent = "Picking…";
        result.setAttribute("aria-busy", "true");
        message.textContent = "Picking a record from your collection…";
        settings.classList.add("hidden");
        let canReroll = false;

        try {
            const params = new URLSearchParams();
            if (previousId !== null) params.set("exclude_release_id", String(previousId));
            if (folderSelect.value !== "0") params.set("folder_id", folderSelect.value);
            const query = params.toString();
            const response = await fetch(`/api/discogs/random${query ? `?${query}` : ""}`, {
                cache: "no-store", signal: controller.signal,
            });
            const data = await response.json();
            if (controller.signal.aborted || request !== controller || !dialog.open) return;
            if (!response.ok || !data.ok) throw new Error(data.error || "Could not pick a record. Please try again.");

            const record = data.release;
            if (!record) {
                previousId = null;
                result.classList.add("hidden");
                if (folderSelect.value !== "0") {
                    message.textContent = "No synced records in this folder. Choose another folder.";
                } else {
                    message.textContent = "No records yet. Connect Discogs and sync your collection in Settings.";
                    settings.classList.remove("hidden");
                }
                return;
            }

            previousId = record.release_id;
            title.textContent = record.title;
            artist.textContent = record.artist;
            cover.classList.add("hidden");
            cover.removeAttribute("src");
            placeholder.classList.remove("hidden");
            coverStatus.textContent = "Cover unavailable";
            cover.alt = `${record.title} — ${record.artist}`;
            // Treat collection metadata as text and allow only web image URLs.
            if (record.cover_url) {
                try {
                    const url = new URL(record.cover_url, window.location.href);
                    if (["http:", "https:"].includes(url.protocol)) {
                        coverStatus.textContent = "Loading cover…";
                        cover.src = url.href;
                    }
                } catch { /* Keep the record visible even without a valid cover. */ }
            }
            result.classList.remove("hidden");
            const count = Number(record.collection_count) || 1;
            canReroll = count > 1;
            message.textContent = canReroll
                ? `${count} records in this selection. Fancy another?`
                : "This is the only record in this selection.";
        } catch (error) {
            if (controller.signal.aborted || request !== controller || !dialog.open) return;
            message.textContent = error.message || "Could not pick a record. Please try again.";
            // Allow retry on a transient network/server failure.
            canReroll = true;
        } finally {
            if (request === controller) {
                request = null;
                reroll.disabled = !canReroll;
                reroll.textContent = "Reroll";
                result.setAttribute("aria-busy", "false");
            }
        }
    }

    folderSelect.addEventListener("change", () => {
        previousId = null;
        request?.abort();
        request = null;
        result.classList.add("hidden");
        pickRecord();
    });
    trigger.addEventListener("click", () => {
        if (trigger.disabled) return;
        result.classList.add("hidden");
        dialog.showModal();
        document.body.classList.add("random-record-open");
        loadFolders();
        pickRecord();
    });
    reroll.addEventListener("click", pickRecord);
    close.addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => {
        request?.abort();
        request = null;
        folderRequest?.abort();
        folderRequest = null;
        cover.removeAttribute("src");
        document.body.classList.remove("random-record-open");
    });
    dialog.addEventListener("click", (event) => {
        if (event.target !== dialog) return;
        const bounds = dialog.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right
            || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
    });
})();
