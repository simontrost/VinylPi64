(() => {
    const trigger = document.getElementById("profileTrigger");
    const triggerName = document.getElementById("profileTriggerName");
    const triggerImage = document.getElementById("profileTriggerImage");
    const triggerFallback = document.getElementById("profileTriggerFallback");
    const dialog = document.getElementById("profileDialog");
    const backdrop = document.getElementById("profileBackdrop");
    const closeButton = document.getElementById("profileDialogClose");
    const dialogTitle = document.getElementById("profileDialogTitle");
    const dialogDescription = document.getElementById("profileDialogDescription");
    const globalMessage = document.getElementById("profileDialogMessage");

    const signedInView = document.getElementById("profileSignedInView");
    const signedOutView = document.getElementById("profileSignedOutView");
    const activeName = document.getElementById("profileActiveName");
    const activeImage = document.getElementById("profileActiveImage");
    const activeInitial = document.getElementById("profileActiveInitial");
    const passwordState = document.getElementById("profilePasswordState");
    const editToggle = document.getElementById("profileEditToggle");
    const logoutButton = document.getElementById("profileLogout");
    const logoutHint = document.getElementById("profileLogoutHint");

    const chooserView = document.getElementById("profileChooserView");
    const list = document.getElementById("profileList");
    const emptyState = document.getElementById("profileEmptyState");
    const createToggle = document.getElementById("profileCreateToggle");

    const loginView = document.getElementById("profileLoginView");
    const loginBack = document.getElementById("profileLoginBack");
    const loginAvatar = document.getElementById("profileLoginAvatar");
    const loginImage = document.getElementById("profileLoginImage");
    const loginInitial = document.getElementById("profileLoginInitial");
    const loginName = document.getElementById("profileLoginName");
    const loginForm = document.getElementById("profileLoginForm");
    const loginPasswordLabel = document.getElementById("profileLoginPasswordLabel");
    const loginPassword = document.getElementById("profileLoginPassword");
    const loginConfirmationField = document.getElementById("profileLoginConfirmationField");
    const loginPasswordConfirmation = document.getElementById("profileLoginPasswordConfirmation");
    const loginSubmit = document.getElementById("profileLoginSubmit");
    const loginMessage = document.getElementById("profileLoginMessage");
    const deleteSelectedButton = document.getElementById("profileDeleteSelected");

    const createView = document.getElementById("profileCreateView");
    const createBack = document.getElementById("profileCreateBack");
    const createForm = document.getElementById("profileCreateForm");
    const nameInput = document.getElementById("profileName");
    const passwordInput = document.getElementById("profilePassword");
    const passwordConfirmationInput = document.getElementById("profilePasswordConfirmation");
    const createAvatarInput = document.getElementById("profileCreateAvatar");
    const createAvatarPreview = document.getElementById("profileCreateAvatarPreview");
    const createAvatarInitial = document.getElementById("profileCreateAvatarInitial");
    const copySettings = document.getElementById("profileCopySettings");
    const createMessage = document.getElementById("profileCreateMessage");

    const editForm = document.getElementById("profileEditForm");
    const editClose = document.getElementById("profileEditCancel");
    const editFormCancel = document.getElementById("profileEditFormCancel");
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
    const editMessage = document.getElementById("profileEditMessage");

    if (!trigger || !dialog) return;

    let state = null;
    let selectedProfile = null;
    let busy = false;
    let editRemoveAvatar = false;
    let editPreviewUrl = null;
    let createPreviewUrl = null;

    function initial(name) {
        return String(name || "Guest").trim().charAt(0).toUpperCase() || "G";
    }

    function setMessage(element, text = "", error = false) {
        if (!element) return;
        element.textContent = text;
        element.classList.toggle("hidden", !text);
        element.classList.toggle("is-error", Boolean(text && error));
    }

    function clearMessages() {
        setMessage(globalMessage);
        setMessage(loginMessage);
        setMessage(createMessage);
        setMessage(editMessage);
        loginPassword.classList.remove("is-invalid");
        loginPasswordConfirmation.classList.remove("is-invalid");
    }

    function friendlyError(error) {
        const text = String(error?.message || error || "Something went wrong.");
        if (text.toLowerCase().includes("incorrect password")) {
            return "That password is incorrect. Please try again.";
        }
        return text;
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
        logoutButton.disabled = busy || Boolean(active?.is_guest) || !Boolean(active?.password_configured);
        editToggle.disabled = busy || Boolean(active?.is_guest);
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

    function createAvatar(name, url, className = "profile-avatar profile-avatar-card") {
        const avatar = document.createElement("span");
        avatar.className = className;
        const img = document.createElement("img");
        img.className = "profile-avatar-image hidden";
        img.alt = "";
        const fallback = document.createElement("span");
        fallback.className = "profile-avatar-fallback";
        avatar.append(img, fallback);
        setImage(img, fallback, name, url);
        return avatar;
    }

    function setDialogCopy(title, description) {
        dialogTitle.textContent = title;
        dialogDescription.textContent = description;
    }

    function showGuestSubview(view) {
        chooserView.classList.toggle("hidden", view !== "chooser");
        loginView.classList.toggle("hidden", view !== "login");
        createView.classList.toggle("hidden", view !== "create");
        clearMessages();

        if (view === "chooser") {
            selectedProfile = null;
            setDialogCopy("Choose a profile", "Select a profile to continue to VinylPi.");
        } else if (view === "login") {
            setDialogCopy("Log in", "Enter the password for the selected profile.");
        } else {
            setDialogCopy("Create account", "Create a separate profile for settings and listening history.");
        }
    }

    function renderProfileChooser(profiles) {
        list.replaceChildren();
        emptyState.classList.toggle("hidden", profiles.length > 0);

        for (const profile of profiles) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "profile-choice-card";
            button.setAttribute("aria-label", `Log in as ${profile.name}`);

            const avatar = createAvatar(profile.name, profile.avatar_url);
            const name = document.createElement("strong");
            name.textContent = profile.name;
            button.append(avatar, name);
            button.addEventListener("click", () => openLogin(profile));
            list.appendChild(button);
        }
    }

    function openLogin(profile) {
        selectedProfile = profile;
        loginName.textContent = profile.name;
        setImage(loginImage, loginInitial, profile.name, profile.avatar_url);
        loginPassword.value = "";
        loginPasswordConfirmation.value = "";
        loginPassword.classList.remove("is-invalid");
        loginPasswordConfirmation.classList.remove("is-invalid");

        const needsInitialPassword = !profile.password_configured;
        loginPasswordLabel.textContent = needsInitialPassword ? "Set a password" : "Password";
        loginPassword.autocomplete = needsInitialPassword ? "new-password" : "current-password";
        loginConfirmationField.classList.toggle("hidden", !needsInitialPassword);
        loginPasswordConfirmation.required = needsInitialPassword;
        loginSubmit.textContent = needsInitialPassword ? "Set password & log in" : "Log in";
        deleteSelectedButton.classList.toggle("hidden", Boolean(profile.is_default));

        showGuestSubview("login");
        window.setTimeout(() => loginPassword.focus(), 40);
    }

    function resetCreateForm() {
        createForm.reset();
        copySettings.checked = true;
        createAvatarInput.value = "";
        clearPreviewUrl("create");
        renderPreview(createAvatarPreview, createAvatarInitial, "Profile", null);
    }

    function render(payload) {
        state = payload;
        const active = payload.active_profile || { name: "Guest", is_guest: true, avatar_url: null };
        triggerName.textContent = active.name;
        setTriggerImage(active.avatar_url);

        const signedIn = !active.is_guest;
        signedInView.classList.toggle("hidden", !signedIn);
        signedOutView.classList.toggle("hidden", signedIn);

        if (signedIn) {
            setDialogCopy("Your profile", "Manage the profile currently used by VinylPi.");
            activeName.textContent = active.name;
            setImage(activeImage, activeInitial, active.name, active.avatar_url);
            passwordState.textContent = active.password_configured
                ? "Password protected"
                : "Set a password before signing out";
            logoutHint.textContent = active.password_configured
                ? "Signing out returns VinylPi to the profile selection."
                : "Set a password in Edit profile before signing out.";
            closeEditForm();
        } else {
            renderProfileChooser(payload.profiles || []);
            showGuestSubview("chooser");
        }
        applyControlState();
    }

    async function loadProfiles() {
        try {
            const payload = await api("/api/profiles");
            render(payload);
        } catch (error) {
            triggerName.textContent = "Profile";
            setMessage(globalMessage, friendlyError(error), true);
        }
    }

    function openDialog() {
        dialog.classList.remove("hidden");
        backdrop.classList.remove("hidden");
        document.body.classList.add("profile-dialog-open");
        clearMessages();
        loadProfiles();
        closeButton.focus();
    }

    function closeDialog() {
        if (busy) return;
        closeEditForm();
        resetCreateForm();
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
        clearMessages();
        editForm.classList.remove("hidden");
        editToggle.classList.add("hidden");
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
        editToggle.classList.remove("hidden");
        editAvatarInput.value = "";
        editRemoveAvatar = false;
        clearPreviewUrl("edit");
        setMessage(editMessage);
    }

    async function loginSelectedProfile() {
        if (!selectedProfile || busy) return;
        const needsInitialPassword = !selectedProfile.password_configured;

        if (needsInitialPassword && loginPassword.value !== loginPasswordConfirmation.value) {
            loginPasswordConfirmation.classList.add("is-invalid");
            setMessage(loginMessage, "The passwords do not match.", true);
            loginPasswordConfirmation.focus();
            return;
        }

        setBusy(true);
        setMessage(loginMessage);
        loginPassword.classList.remove("is-invalid");
        loginPasswordConfirmation.classList.remove("is-invalid");

        try {
            if (needsInitialPassword) {
                await api(`/api/profiles/${encodeURIComponent(selectedProfile.id)}/initialize-password`, {
                    method: "POST",
                    body: JSON.stringify({
                        password: loginPassword.value,
                        password_confirmation: loginPasswordConfirmation.value,
                    }),
                });
            } else {
                await api(`/api/profiles/${encodeURIComponent(selectedProfile.id)}/activate`, {
                    method: "POST",
                    body: JSON.stringify({ password: loginPassword.value }),
                });
            }
            window.location.reload();
        } catch (error) {
            const text = friendlyError(error);
            loginPassword.classList.add("is-invalid");
            loginView.classList.remove("profile-auth-error-shake");
            void loginView.offsetWidth;
            loginView.classList.add("profile-auth-error-shake");
            setMessage(loginMessage, text, true);
            setBusy(false);
            loginPassword.focus();
            loginPassword.select();
        }
    }

    async function deleteSelectedProfile() {
        const profile = selectedProfile;
        if (!profile || profile.is_default || busy) return;
        if (!window.confirm(`Delete profile “${profile.name}” and all of its statistics, settings and profile image?`)) return;

        setBusy(true);
        setMessage(loginMessage);
        try {
            await api(`/api/profiles/${encodeURIComponent(profile.id)}`, { method: "DELETE" });
            const payload = await api("/api/profiles");
            render(payload);
            setMessage(globalMessage, `Profile “${profile.name}” deleted.`);
        } catch (error) {
            setMessage(loginMessage, friendlyError(error), true);
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

    editToggle.addEventListener("click", openEditForm);
    editClose.addEventListener("click", closeEditForm);
    editFormCancel.addEventListener("click", closeEditForm);

    loginBack.addEventListener("click", () => showGuestSubview("chooser"));
    createToggle.addEventListener("click", () => {
        resetCreateForm();
        showGuestSubview("create");
        window.setTimeout(() => nameInput.focus(), 40);
    });
    createBack.addEventListener("click", () => {
        resetCreateForm();
        showGuestSubview("chooser");
    });
    deleteSelectedButton.addEventListener("click", deleteSelectedProfile);

    nameInput.addEventListener("input", () => {
        createAvatarInitial.textContent = initial(nameInput.value || "Profile");
    });
    editName.addEventListener("input", () => {
        editAvatarInitial.textContent = initial(editName.value || "Profile");
    });
    loginPassword.addEventListener("input", () => {
        loginPassword.classList.remove("is-invalid");
        setMessage(loginMessage);
    });
    loginPasswordConfirmation.addEventListener("input", () => {
        loginPasswordConfirmation.classList.remove("is-invalid");
        setMessage(loginMessage);
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

    loginForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        await loginSelectedProfile();
    });

    createForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (busy) return;
        setMessage(createMessage);

        if (passwordInput.value !== passwordConfirmationInput.value) {
            passwordConfirmationInput.classList.add("is-invalid");
            setMessage(createMessage, "The passwords do not match.", true);
            passwordConfirmationInput.focus();
            return;
        }

        setBusy(true);
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
            setMessage(createMessage, friendlyError(error), true);
            setBusy(false);
            nameInput.focus();
        }
    });

    editForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (busy || !state?.active_profile || state.active_profile.is_guest) return;
        setMessage(editMessage);

        if (newPassword.value !== newPasswordConfirmation.value) {
            newPasswordConfirmation.classList.add("is-invalid");
            setMessage(editMessage, "The new passwords do not match.", true);
            newPasswordConfirmation.focus();
            return;
        }
        if (!state.active_profile.password_configured && !newPassword.value) {
            newPassword.classList.add("is-invalid");
            setMessage(editMessage, "Set a password before saving this profile.", true);
            newPassword.focus();
            return;
        }

        setBusy(true);
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
            const payload = await api("/api/profiles");
            render(payload);
            setMessage(globalMessage, "Profile updated.");
        } catch (error) {
            setMessage(editMessage, friendlyError(error), true);
            setBusy(false);
            return;
        }
        setBusy(false);
    });

    logoutButton.addEventListener("click", async () => {
        if (busy || state?.active_profile?.is_guest) return;
        setBusy(true);
        clearMessages();
        try {
            await api("/api/profiles/logout", { method: "POST" });
            window.location.reload();
        } catch (error) {
            setMessage(globalMessage, friendlyError(error), true);
            setBusy(false);
        }
    });

    loadProfiles();
})();
