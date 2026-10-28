/* A successful /api/source POST must not generate a spurious source error. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const code = fs.readFileSync(path.join(__dirname, '../web/static/js/pages/spotify_dashboard.js'), 'utf8');
const buttons = ['off', 'vinyl', 'spotify'].map(mode => ({
    dataset: { sourceMode: mode },
    disabled: false,
    classList: { toggle() {}, add() {}, remove() {} },
    setAttribute() {},
    addEventListener() {},
}));
let source = 'off';
const feedback = { textContent: '', classList: { toggle() {}, remove() {}, add() {} } };
const context = {
    document: {
        querySelectorAll: () => buttons,
        querySelector: () => null,
        getElementById: id => id === 'spotify-feedback' ? feedback : null,
        addEventListener() {},
        dispatchEvent() {},
    },
    CustomEvent: class { constructor(name, opts) { this.type = name; this.detail = opts.detail; } },
    window: { setInterval: () => 1, clearInterval() {} },
    fetch: async (url, options) => {
        if (url === '/api/source' && options?.method === 'POST') {
            source = JSON.parse(options.body).mode;
        }
        assert.equal(url, '/api/source');
        return { ok: true, json: async () => ({ ok: true, mode: source, spotify: { connected: true, configured: true } }) };
    },
    renderDiscogsContext() {}, showTrackInfo() {},
    setText() {}, loadStatus: async () => {},
    currentTrackKey: null, CURRENT_TRACK: {},
    console,
};
vm.createContext(context);
vm.runInContext(code, context);
(async () => {
    for (const mode of ['vinyl', 'spotify', 'off']) {
        await vm.runInContext(`setSourceMode('${mode}')`, context);
        assert.equal(source, mode);
        assert.equal(feedback.textContent, '', `unexpected UI error after switching to ${mode}`);
        assert.ok(buttons.every(b => !b.disabled));
    }
    console.log('Source UI: successful Vinyl/Spotify/Off changes preserve the selector and show no error');
})().catch(error => { console.error(error); process.exitCode = 1; });
