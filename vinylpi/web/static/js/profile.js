(() => {
    const trigger = document.getElementById("profileTrigger");
    const triggerName = document.getElementById("profileTriggerName");
    const triggerImage = document.getElementById("profileTriggerImage");
    const triggerFallback = document.getElementById("profileTriggerFallback");
    const dialog = document.getElementById("profileDialog");
    const backdrop = document.getElementById("profileBackdrop");
    const closeButton = document.getElementById("profileDialogClose");
    const list = document.getElementById("profileList");
    const activeName = document.getElementById("profileActiveName");
    const activeAvatar = document.getElementById("profileActiveAvatar");
    const activeImage = document.getElementById("profileActiveImage");
    const activeInitial = document.getElementById("profileActiveInitial");
    const activeBadge = document.getElementById("profileActiveBadge");
    const passwordState = document.getElementById("profilePasswordState");
    const editToggle = document.getElementById("profileEditToggle");
    const editForm = document.getElementById("profileEditForm");
    const editCancel = document.getElementById("profileEditCancel");
    const editName = document.getElementById("profileEditName");
    const currentPasswordField = document.getElementById("profileCurrentPasswordField");
    const currentPassword = document.getElementById("profileCurrentPassword");
    const newPasswordLabel = document.getElementById("profileNewPasswordLabel");
    const newPassword = document.getElementById("profileNewPassword");
    const newPasswordConfirmation = document.getElementById("profileNewPasswordConfirmation");
    const editAvatarInput = document.getElementById("profileEditAvatar");
    const editAvatarPreview = document.getElementById("profileEditAvatarPreview");
    const editAvatarInitial = document.getElementById("profileEditAvatarInitial");
    const removeAvatarButton = document.getElementById("profileRemoveAvatar");
    const createForm = document.getElementById("profileCreateForm");
    const nameInput = document.getElementById("profileName");
    const passwordInput = document.getElementById("profilePassword");
    const passwordConfirmationInput = document.getElementById("profilePasswordConfirmation");
    const createAvatarInput = document.getElementById("profileCreateAvatar");
    const createAvatarPreview = document.getElementById("profileCreateAvatarPreview");
    const createAvatarInitial = document.getElementById("profileCreateAvatarInitial");
    const copySettings = document.getElementById("profileCopySettings");
    const logoutButton = document.getElementById("profileLogout");
    const logoutHint = document.getElementById("profileLogoutHint");
    const message = document.getElementById("profileDialogMessage");

    if (!trigger || !dialog) return;

    let state = null;
    let busy = false;
    let editRemoveAvatar = false;
    let editPreviewUrl = null;
    let createPreviewUrl = null;

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
        const isFormData = options.body instanceof FormData;
        const headers = isFormData
            ? { ...(options.headers || {}) }
            : { "Content-Type": "application/json", ...(options.headers || {}) };
        const response = await fetch(url, { ...options, headers });
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
        if (!value) applyControlState();
    }

    function applyControlState() {
        const active = state?.active_profile;
        logoutButton.disabled = Boolean(active?.is_guest) || !Boolean(active?.password_configured) || busy;
        editToggle.disabled = Boolean(active?.is_guest) || busy;
        removeAvatarButton.disabled = busy || (!active?.avatar_url && !editAvatarInput.files?.length);
    }

    function setImage(img, fallback, name, url) {
        fallback.textContent = initial(name);
        if (!url) {
            img.removeAttribute("src");
            img.classList.add("hidden");
            fallback.classList.remove("hidden");
            return;
        }
        img.onload = () => {
            img.classList.remove("hidden");
            fallback.classList.add("hidden");
        };
        img.onerror = () => {
            img.classList.add("hidden");
            fallback.classList.remove("hidden");
        };
        img.src = url;
    }

    function setTriggerImage(url) {
        if (!url) {
            triggerImage.removeAttribute("src");
            triggerImage.classList.add("hidden");
            triggerFallback.classList.remove("hidden");
            return;
        }
        triggerImage.onload = () => {
            triggerImage.classList.remove("hidden");
            triggerFallback.classList.add("hidden");
        };
        triggerImage.onerror = () => {
            triggerImage.classList.add("hidden");
            triggerFallback.classList.remove("hidden");
        };
        triggerImage.src = url;
    }

    function createAvatar(name, url) {
        const avatar = document.createElement("span");
        avatar.className = "profile-avatar profile-avatar-small";
        const img = document.createElement("img");
        img.className = "profile-avatar-image hidden";
        img.alt = "";
        const fallback = document.createElement("span");
        fallback.className = "profile-avatar-fallback";
        avatar.append(img, fallback);
        setImage(img, fallback, name, url);
        return avatar;
    }

    function createLoginForm(profile) {
        const form = document.createElement("form");
        form.className = "profile-login-form hidden";

        const fields = document.createElement("div");
        fields.className = "profile-login-fields";

        const label = document.createElement("label");
        label.className = "profile-field";
        const labelText = document.createElement("span");
        labelText.textContent = profile.password_configured
            ? `Password for ${profile.name}`
            : `Set password for ${profile.name}`;
        const input = document.createElement("input");
        input.type = "password";
        input.minLength = 4;
        input.maxLength = 128;
        input.autocomplete = profile.password_configured ? "current-password" : "new-password";
        input.required = true;
        label.append(labelText, input);
        fields.appendChild(label);

        let confirmationInput = null;
        if (!profile.password_configured) {
            const confirmationLabel = document.createElement("label");
            confirmationLabel.className = "profile-field";
            const confirmationText = document.createElement("span");
            confirmationText.textContent = "Confirm password";
            confirmationInput = document.createElement("input");
            confirmationInput.type = "password";
            confirmationInput.minLength = 4;
            confirmationInput.maxLength = 128;
            confirmationInput.autocomplete = "new-password";
            confirmationInput.required = true;
            confirmationLabel.append(confirmationText, confirmationInput);
            fields.appendChild(confirmationLabel);
        }

        const actions = document.createElement("div");
        actions.className = "profile-login-actions";
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.textContent = "Cancel";
        cancel.addEventListener("click", () => {
            form.classList.add("hidden");
            input.value = "";
            if (confirmationInput) confirmationInput.value = "";
        });
        const submit = document.createElement("button");
        submit.type = "submit";
        submit.className = "btn-primary";
        submit.textContent = profile.password_configured ? "Log in" : "Set & log in";
        actions.append(cancel, submit);
        form.append(fields, actions);

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (profile.password_configured) {
                await loginProfile(profile.id, input.value);
                return;
            }
            if (input.value !== confirmationInput.value) {
                showMessage("Passwords do not match.", true);
                confirmationInput.focus();
                return;
            }
            await initializeLegacyProfile(profile.id, input.value, confirmationInput.value);
        });
        return { form, input };
    }

    function renderProfile(profile) {
        const card = document.createElement("div");
        card.className = "profile-list-card";

        const row = document.createElement("div");
        row.className = "profile-list-item";
        if (profile.is_active) row.classList.add("is-active");

        const avatar = createAvatar(profile.name, profile.avatar_url);
        const copy = document.createElement("div");
        copy.className = "profile-list-copy";
        const title = document.createElement("strong");
        title.textContent = profile.name;
        const meta = document.createElement("span");
        if (profile.is_active) {
            meta.textContent = profile.password_configured ? "Active profile" : "Set a password before signing out";
        } else if (profile.password_configured) {
            meta.textContent = "Password required to log in";
        } else {
            meta.textContent = "Password setup pending";
        }
        copy.append(title, meta);

        const actions = document.createElement("div");
        actions.className = "profile-list-actions";

        if (profile.is_active) {
            const badge = document.createElement("span");
            badge.className = "profile-row-badge";
            badge.textContent = "Active";
            actions.appendChild(badge);
        } else {
            const { form, input } = createLoginForm(profile);
            const loginButton = document.createElement("button");
            loginButton.type = "button";
            loginButton.textContent = profile.password_configured ? "Log in" : "Set password";
            loginButton.title = profile.password_configured
                ? "Log in to profile"
                : "Set an initial password for this existing profile";
            loginButton.addEventListener("click", () => {
                form.classList.toggle("hidden");
                if (!form.classList.contains("hidden")) input.focus();
            });
            actions.appendChild(loginButton);
            card.append(row, form);
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
        if (!card.contains(row)) card.appendChild(row);
        return card;
    }

    function render(payload) {
        state = payload;
        const active = payload.active_profile || { name: "Guest", is_guest: true, avatar_url: null };
        triggerName.textContent = active.name;
        setTriggerImage(active.avatar_url);
        activeName.textContent = active.name;
        setImage(activeImage, activeInitial, active.name, active.avatar_url);
        activeBadge.textContent = active.is_guest ? "Guest mode" : "Signed in";
        activeBadge.classList.toggle("is-guest", Boolean(active.is_guest));
        editToggle.classList.toggle("hidden", Boolean(active.is_guest));

        if (active.is_guest) {
            passwordState.textContent = "No personal profile is currently active.";
            logoutHint.textContent = "Choose a profile above and enter its password to log in.";
        } else if (active.password_configured) {
            passwordState.textContent = "Password protected";
            logoutHint.textContent = "Signing out switches VinylPi to a separate guest database.";
        } else {
            passwordState.textContent = "Password not set";
            logoutHint.textContent = "Set a password in Edit profile before signing out.";
        }

        list.replaceChildren();
        for (const profile of payload.profiles || []) {
            list.appendChild(renderProfile(profile));
        }
        applyControlState();
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
        closeEditForm();
        dialog.classList.add("hidden");
        backdrop.classList.add("hidden");
        document.body.classList.remove("profile-dialog-open");
        trigger.focus();
    }

    function clearPreviewUrl(kind) {
        if (kind === "edit" && editPreviewUrl) {
            URL.revokeObjectURL(editPreviewUrl);
            editPreviewUrl = null;
        }
        if (kind === "create" && createPreviewUrl) {
            URL.revokeObjectURL(createPreviewUrl);
            createPreviewUrl = null;
        }
    }

    function renderPreview(container, fallback, name, url) {
        let img = container.querySelector("img");
        if (!img) {
            img = document.createElement("img");
            img.className = "profile-avatar-image hidden";
            img.alt = "";
            container.prepend(img);
        }
        setImage(img, fallback, name, url);
    }

    function openEditForm() {
        const active = state?.active_profile;
        if (!active || active.is_guest) return;
        clearMessage();
        editForm.classList.remove("hidden");
        editName.value = active.name;
        currentPassword.value = "";
        newPassword.value = "";
        newPasswordConfirmation.value = "";
        editAvatarInput.value = "";
        editRemoveAvatar = false;
        clearPreviewUrl("edit");
        currentPasswordField.classList.toggle("hidden", !active.password_configured);
        currentPassword.required = Boolean(active.password_configured);
        newPassword.required = !active.password_configured;
        newPasswordConfirmation.required = !active.password_configured;
        newPasswordLabel.textContent = active.password_configured ? "New password (optional)" : "Set password";
        renderPreview(editAvatarPreview, editAvatarInitial, active.name, active.avatar_url);
        removeAvatarButton.classList.toggle("hidden", !active.avatar_url);
        applyControlState();
        editName.focus();
    }

    function closeEditForm() {
        editForm.classList.add("hidden");
        editAvatarInput.value = "";
        editRemoveAvatar = false;
        clearPreviewUrl("edit");
    }

    async function loginProfile(profileId, password) {
        if (busy) return;
        setBusy(true);
        clearMessage();
        try {
            await api(`/api/profiles/${encodeURIComponent(profileId)}/activate`, {
                method: "POST",
                body: JSON.stringify({ password }),
            });
            window.location.reload();
        } catch (error) {
            showMessage(error.message, true);
            setBusy(false);
        }
    }

    async function initializeLegacyProfile(profileId, password, passwordConfirmation) {
        if (busy) return;
        setBusy(true);
        clearMessage();
        try {
            await api(`/api/profiles/${encodeURIComponent(profileId)}/initialize-password`, {
                method: "POST",
                body: JSON.stringify({
                    password,
                    password_confirmation: passwordConfirmation,
                }),
            });
            window.location.reload();
        } catch (error) {
            showMessage(error.message, true);
            setBusy(false);
        }
    }

    async function deleteProfile(profile) {
        if (busy || !window.confirm(`Delete profile “${profile.name}” and all of its statistics, settings and profile image?`)) return;
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
    editToggle.addEventListener("click", openEditForm);
    editCancel.addEventListener("click", closeEditForm);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !dialog.classList.contains("hidden")) closeDialog();
    });

    nameInput.addEventListener("input", () => {
        createAvatarInitial.textContent = initial(nameInput.value || "Profile");
    });
    editName.addEventListener("input", () => {
        editAvatarInitial.textContent = initial(editName.value || "Profile");
    });

    createAvatarInput.addEventListener("change", () => {
        clearPreviewUrl("create");
        const file = createAvatarInput.files?.[0];
        if (!file) {
            renderPreview(createAvatarPreview, createAvatarInitial, nameInput.value || "Profile", null);
            return;
        }
        createPreviewUrl = URL.createObjectURL(file);
        renderPreview(createAvatarPreview, createAvatarInitial, nameInput.value || "Profile", createPreviewUrl);
    });

    editAvatarInput.addEventListener("change", () => {
        clearPreviewUrl("edit");
        const file = editAvatarInput.files?.[0];
        editRemoveAvatar = false;
        if (!file) {
            const active = state?.active_profile;
            renderPreview(editAvatarPreview, editAvatarInitial, editName.value || active?.name, active?.avatar_url);
        } else {
            editPreviewUrl = URL.createObjectURL(file);
            renderPreview(editAvatarPreview, editAvatarInitial, editName.value || "Profile", editPreviewUrl);
        }
        removeAvatarButton.classList.remove("hidden");
        applyControlState();
    });

    removeAvatarButton.addEventListener("click", () => {
        editRemoveAvatar = true;
        editAvatarInput.value = "";
        clearPreviewUrl("edit");
        renderPreview(editAvatarPreview, editAvatarInitial, editName.value || "Profile", null);
        removeAvatarButton.classList.add("hidden");
    });

    createForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (busy) return;
        if (passwordInput.value !== passwordConfirmationInput.value) {
            showMessage("Passwords do not match.", true);
            passwordConfirmationInput.focus();
            return;
        }
        setBusy(true);
        clearMessage();
        const formData = new FormData();
        formData.append("name", nameInput.value);
        formData.append("password", passwordInput.value);
        formData.append("password_confirmation", passwordConfirmationInput.value);
        formData.append("copy_current_settings", String(copySettings.checked));
        formData.append("activate", "true");
        if (createAvatarInput.files?.[0]) formData.append("avatar", createAvatarInput.files[0]);

        try {
            await api("/api/profiles", { method: "POST", body: formData });
            window.location.reload();
        } catch (error) {
            showMessage(error.message, true);
            setBusy(false);
            nameInput.focus();
        }
    });

    editForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (busy || !state?.active_profile || state.active_profile.is_guest) return;
        if (newPassword.value !== newPasswordConfirmation.value) {
            showMessage("New passwords do not match.", true);
            newPasswordConfirmation.focus();
            return;
        }
        if (!state.active_profile.password_configured && !newPassword.value) {
            showMessage("Set a password before saving this legacy profile.", true);
            newPassword.focus();
            return;
        }

        setBusy(true);
        clearMessage();
        const formData = new FormData();
        formData.append("name", editName.value);
        formData.append("current_password", currentPassword.value);
        formData.append("new_password", newPassword.value);
        formData.append("new_password_confirmation", newPasswordConfirmation.value);
        formData.append("remove_avatar", String(editRemoveAvatar));
        if (editAvatarInput.files?.[0]) formData.append("avatar", editAvatarInput.files[0]);

        try {
            await api(`/api/profiles/${encodeURIComponent(state.active_profile.id)}`, {
                method: "PATCH",
                body: formData,
            });
            closeEditForm();
            await loadProfiles();
            showMessage("Profile updated.");
        } catch (error) {
            showMessage(error.message, true);
        } finally {
            setBusy(false);
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
