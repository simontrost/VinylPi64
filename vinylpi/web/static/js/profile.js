(() => {
    const trigger = document.getElementById("profileTrigger");
    const triggerName = document.getElementById("profileTriggerName");
    const dialog = document.getElementById("profileDialog");
    const backdrop = document.getElementById("profileBackdrop");
    const closeButton = document.getElementById("profileDialogClose");
    const list = document.getElementById("profileList");
    const activeName = document.getElementById("profileActiveName");
    const activeAvatar = document.getElementById("profileActiveAvatar");
    const activeBadge = document.getElementById("profileActiveBadge");
    const createForm = document.getElementById("profileCreateForm");
    const nameInput = document.getElementById("profileName");
    const copySettings = document.getElementById("profileCopySettings");
    const logoutButton = document.getElementById("profileLogout");
    const message = document.getElementById("profileDialogMessage");

    if (!trigger || !dialog) return;

    let state = null;
    let busy = false;

    function initial(name) {
        return String(name || "Guest").trim().charAt(0).toUpperCase() || "G";
    }

    function showMessage(text, error = false) {
        message.textContent = text;
        message.classList.remove("hidden", "is-error");
        if (error) message.classList.add("is-error");
    }

    function clearMessage() {
        message.textContent = "";
        message.classList.add("hidden");
        message.classList.remove("is-error");
    }

    async function api(url, options = {}) {
        const response = await fetch(url, {
            headers: { "Content-Type": "application/json", ...(options.headers || {}) },
            ...options,
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.ok === false) {
            throw new Error(payload.error || `Request failed (${response.status})`);
        }
        return payload;
    }

    function setBusy(value) {
        busy = value;
        dialog.classList.toggle("is-busy", value);
        dialog.querySelectorAll("button, input").forEach((element) => {
            element.disabled = value;
        });
        if (!value && state?.active_profile?.is_guest) logoutButton.disabled = true;
    }

    function renderProfile(profile, activeProfile) {
        const row = document.createElement("div");
        row.className = "profile-list-item";
        if (profile.is_active) row.classList.add("is-active");

        const avatar = document.createElement("span");
        avatar.className = "profile-avatar profile-avatar-small";
        avatar.textContent = initial(profile.name);

        const copy = document.createElement("div");
        copy.className = "profile-list-copy";
        const title = document.createElement("strong");
        title.textContent = profile.name;
        const meta = document.createElement("span");
        meta.textContent = profile.is_active ? "Active profile" : "Separate settings and statistics";
        copy.append(title, meta);

        const actions = document.createElement("div");
        actions.className = "profile-list-actions";

        if (profile.is_active) {
            const badge = document.createElement("span");
            badge.className = "profile-row-badge";
            badge.textContent = "Active";
            actions.appendChild(badge);
        } else {
            const switchButton = document.createElement("button");
            switchButton.type = "button";
            switchButton.textContent = "Switch";
            switchButton.addEventListener("click", () => switchProfile(profile.id));
            actions.appendChild(switchButton);
        }

        if (!profile.is_default && !profile.is_active) {
            const deleteButton = document.createElement("button");
            deleteButton.type = "button";
            deleteButton.className = "profile-delete-button";
            deleteButton.setAttribute("aria-label", `Delete ${profile.name}`);
            deleteButton.title = "Delete profile";
            deleteButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="M7 7l1 13h8l1-13"></path></svg>';
            deleteButton.addEventListener("click", () => deleteProfile(profile));
            actions.appendChild(deleteButton);
        }

        row.append(avatar, copy, actions);
        return row;
    }

    function render(payload) {
        state = payload;
        const active = payload.active_profile || { name: "Guest", is_guest: true };
        triggerName.textContent = active.name;
        activeName.textContent = active.name;
        activeAvatar.textContent = initial(active.name);
        activeBadge.textContent = active.is_guest ? "Guest mode" : "Signed in";
        activeBadge.classList.toggle("is-guest", Boolean(active.is_guest));
        logoutButton.disabled = Boolean(active.is_guest) || busy;

        list.replaceChildren();
        for (const profile of payload.profiles || []) {
            list.appendChild(renderProfile(profile, active));
        }
    }

    async function loadProfiles() {
        try {
            const payload = await api("/api/profiles");
            render(payload);
        } catch (error) {
            triggerName.textContent = "Profile";
            showMessage(error.message, true);
        }
    }

    function openDialog() {
        dialog.classList.remove("hidden");
        backdrop.classList.remove("hidden");
        document.body.classList.add("profile-dialog-open");
        clearMessage();
        loadProfiles();
        closeButton.focus();
    }

    function closeDialog() {
        if (busy) return;
        dialog.classList.add("hidden");
        backdrop.classList.add("hidden");
        document.body.classList.remove("profile-dialog-open");
        trigger.focus();
    }

    async function switchProfile(profileId) {
        if (busy) return;
        setBusy(true);
        clearMessage();
        try {
            await api(`/api/profiles/${encodeURIComponent(profileId)}/activate`, { method: "POST" });
            window.location.reload();
        } catch (error) {
            showMessage(error.message, true);
            setBusy(false);
        }
    }

    async function deleteProfile(profile) {
        if (busy || !window.confirm(`Delete profile “${profile.name}” and all of its statistics and settings?`)) return;
        setBusy(true);
        clearMessage();
        try {
            await api(`/api/profiles/${encodeURIComponent(profile.id)}`, { method: "DELETE" });
            await loadProfiles();
            showMessage(`Profile “${profile.name}” deleted.`);
        } catch (error) {
            showMessage(error.message, true);
        } finally {
            setBusy(false);
        }
    }

    trigger.addEventListener("click", openDialog);
    closeButton.addEventListener("click", closeDialog);
    backdrop.addEventListener("click", closeDialog);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !dialog.classList.contains("hidden")) closeDialog();
    });

    createForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (busy) return;
        setBusy(true);
        clearMessage();
        try {
            await api("/api/profiles", {
                method: "POST",
                body: JSON.stringify({
                    name: nameInput.value,
                    copy_current_settings: copySettings.checked,
                    activate: true,
                }),
            });
            window.location.reload();
        } catch (error) {
            showMessage(error.message, true);
            setBusy(false);
            nameInput.focus();
        }
    });

    logoutButton.addEventListener("click", async () => {
        if (busy || state?.active_profile?.is_guest) return;
        setBusy(true);
        clearMessage();
        try {
            await api("/api/profiles/logout", { method: "POST" });
            window.location.reload();
        } catch (error) {
            showMessage(error.message, true);
            setBusy(false);
        }
    });

    loadProfiles();
})();
