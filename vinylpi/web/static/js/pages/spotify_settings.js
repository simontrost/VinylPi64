/* Profile-specific Spotify account management on Settings. */

function setSpotifySettingsFeedback(message = "", isError = false) {
    const element = document.getElementById("spotifySettingsFeedback");
    if (!element) return;
    element.textContent = message;
    element.classList.toggle("spotify-settings-error", Boolean(isError));
}

function renderSpotifySettings(status = {}) {
    const configured = Boolean(status.configured);
    const connected = Boolean(status.connected);
    const account = status.account || {};

    const dot = document.getElementById("spotifySettingsStatusDot");
    const title = document.getElementById("spotifySettingsStatusTitle");
    const copy = document.getElementById("spotifySettingsStatusCopy");
    const connect = document.getElementById("spotifySettingsConnect");
    const disconnect = document.getElementById("spotifySettingsDisconnect");
    const appStatus = document.getElementById("spotifySettingsAppStatus");
    const redirect = document.getElementById("spotifySettingsRedirect");

    dot?.classList.toggle("connected", connected);

    if (title) {
        if (connected) {
            title.textContent = account.display_name
                ? `Connected as ${account.display_name}`
                : "Spotify account connected";
        } else {
            title.textContent = configured ? "No Spotify account connected" : "Spotify app not configured";
        }
    }

    if (copy) {
        if (connected) {
            const detail = account.spotify_user_id || account.account_id || "";
            copy.textContent = detail
                ? `This account is linked only to the current VinylPi profile · ${detail}`
                : "This account is linked only to the current VinylPi profile.";
        } else if (configured) {
            copy.textContent = "Connect the Spotify account that should belong to the current VinylPi profile.";
        } else {
            copy.textContent = "Add the Spotify app credentials to vinylpi.env before connecting an account.";
        }
    }

    if (connect) {
        connect.disabled = !configured;
        connect.textContent = connected ? "Change account" : "Connect Spotify";
        connect.dataset.connected = connected ? "true" : "false";
    }
    if (disconnect) disconnect.disabled = !connected;

    if (appStatus) {
        appStatus.innerHTML = configured
            ? 'Spotify app credentials found in <strong>vinylpi.env</strong>'
            : 'Spotify app credentials missing in <strong>vinylpi.env</strong>';
    }
    if (redirect) {
        redirect.textContent = status.redirect_uri
            ? `Redirect URI: ${status.redirect_uri}`
            : "SPOTIFY_REDIRECT_URI is not configured.";
    }
}

async function loadSpotifySettingsStatus() {
    try {
        const response = await fetch("/api/spotify/status", { cache: "no-store" });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "Spotify status unavailable");
        renderSpotifySettings(data);
    } catch (error) {
        console.error(error);
        setSpotifySettingsFeedback(error.message || "Could not load Spotify status.", true);
    }
}

async function connectSpotifyFromSettings() {
    const button = document.getElementById("spotifySettingsConnect");
    if (!button) return;
    button.disabled = true;
    setSpotifySettingsFeedback("Opening Spotify authorization…");

    const force = button.dataset.connected === "true" ? "&force=1" : "";
    try {
        const response = await fetch(`/api/spotify/auth-url?return_to=settings${force}`, { cache: "no-store" });
        const data = await response.json();
        if (!response.ok || !data.ok || !data.auth_url) {
            throw new Error(data.error || "Spotify authorization URL unavailable.");
        }
        window.location.assign(data.auth_url);
    } catch (error) {
        console.error(error);
        setSpotifySettingsFeedback(error.message || "Could not start Spotify authorization.", true);
        button.disabled = false;
    }
}

async function disconnectSpotifyFromSettings() {
    if (!window.confirm("Disconnect Spotify from this VinylPi profile?")) return;
    const button = document.getElementById("spotifySettingsDisconnect");
    if (button) button.disabled = true;
    setSpotifySettingsFeedback("Disconnecting Spotify…");

    try {
        const response = await fetch("/api/spotify/disconnect", { method: "POST" });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "Could not disconnect Spotify");
        setSpotifySettingsFeedback("Spotify disconnected from this profile.");
        renderSpotifySettings(data);
    } catch (error) {
        console.error(error);
        setSpotifySettingsFeedback(error.message || "Could not disconnect Spotify.", true);
    } finally {
        await loadSpotifySettingsStatus();
    }
}

function consumeSpotifySettingsCallback() {
    const url = new URL(window.location.href);
    const result = url.searchParams.get("spotify");
    if (!result) return;

    if (result === "connected") {
        setSpotifySettingsFeedback("Spotify account connected to this profile.");
    } else {
        const reason = url.searchParams.get("reason") || "authorization_failed";
        setSpotifySettingsFeedback(`Spotify connection failed: ${reason.replaceAll("_", " ")}.`, true);
    }

    url.searchParams.delete("spotify");
    url.searchParams.delete("reason");
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("spotifySettingsConnect")?.addEventListener("click", connectSpotifyFromSettings);
    document.getElementById("spotifySettingsDisconnect")?.addEventListener("click", disconnectSpotifyFromSettings);
    consumeSpotifySettingsCallback();
    loadSpotifySettingsStatus();
});
