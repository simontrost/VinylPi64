/* Browser-independent regression test for log UI state and history controls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync(require('node:path').join(__dirname, '../web/static/js/pages/logs.js'), 'utf8');
const events = [
    { id: 1, timestamp: 1792750000, level: 'WARNING', source: 'Test', message: 'Old warning' },
    { id: 2, timestamp: 1792750100, level: 'DEBUG', source: 'Test', message: 'Old debug' },
];
let cutoff = 0;
const storage = new Map();

class Element {
    constructor(tag = 'div') {
        this.tag = tag;
        this.value = tag === 'select' ? 'issues' : '';
        this.textContent = '';
        this.children = [];
        this.listeners = {};
        this.dataset = {};
        this.scrollHeight = 100;
        this.scrollTop = 0;
        this.clientHeight = 100;
        this.hidden = false;
        this.disabled = false;
    }
    addEventListener(event, cb) { (this.listeners[event] ||= []).push(cb); }
    async fire(event) { return Promise.all((this.listeners[event] || []).map(cb => cb())); }
    setAttribute(key, value) { this[key] = value; }
    append(...items) {
        for (const item of items) {
            if (item.tag === 'fragment') this.children.push(...item.children);
            else this.children.push(item);
        }
    }
    replaceChildren(...items) { this.children = []; this.append(...items); }
    get firstChild() { return this.children[0] || null; }
    get firstElementChild() { return this.firstChild; }
    remove() { /* Unused by regression scenario. */ }
}

const ids = ['logsStream', 'logsLevel', 'logsSearch', 'logsToggleLive', 'logsLiveStatus',
    'logsLiveDot', 'logsCount', 'logsFeedback', 'logsCopy', 'logsClear', 'logsHistory',
    'logsNew', 'logsVerbose', 'logsVerboseHelp'];
function buildBrowser() {
    const elements = Object.fromEntries(ids.map(id => [id, new Element(id)]));
    elements.logsLevel.value = 'all';
    const document = {
        hidden: false,
        getElementById: id => elements[id],
        createElement: tag => new Element(tag),
        createDocumentFragment: () => new Element('fragment'),
        addEventListener: () => {},
    };
    const fetch = async (url, opts = {}) => {
        if (url.startsWith('/api/config')) return {ok:true, json: async () => ({debug:{logs:false}})};
        if (url === '/api/logs/clear') {
            assert.equal(opts.method, 'POST');
            cutoff = events.at(-1)?.id || 0;
            return {ok:true, json: async () => ({ok:true, cleared_through: cutoff})};
        }
        if (url.startsWith('/api/logs?')) {
            const q = new URL(url, 'http://localhost/').searchParams;
            const after = Number(q.get('after'));
            let found = events.filter(e => e.id > after && (q.get('history') === '1' || e.id > cutoff));
            const level = q.get('level');
            if (level === 'issues') found = found.filter(e => ['WARNING', 'ERROR'].includes(e.level));
            if (level === 'warnings') found = found.filter(e => e.level === 'WARNING');
            if (level === 'errors') found = found.filter(e => e.level === 'ERROR');
            if (level === 'info') found = found.filter(e => e.level === 'INFO');
            if (level === 'debug') found = found.filter(e => e.level === 'DEBUG');
            if (!after) found = found.slice(-200);
            return {ok:true, json: async () => ({ok:true, entries:found})};
        }
        throw Error(`unexpected URL ${url}`);
    };
    vm.runInNewContext(script, {
        document, fetch, URL, URLSearchParams, Date, Number, String, Math, Set,
        localStorage: {
            getItem: key => storage.get(key) ?? null,
            setItem: (key, value) => storage.set(key, value),
        },
        navigator:{clipboard:{writeText:async()=>{}}},
        setInterval:()=>0, setTimeout:()=>0, clearTimeout:()=>{},
    });
    return elements;
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const visibleEntries = els => els.logsStream.children.filter(e => e.className === 'log-entry').length;

(async () => {
    let els = buildBrowser();
    await settle();
    assert.equal(visibleEntries(els), 2, 'default all-messages filter');
    els.logsLevel.value = 'all';
    await els.logsLevel.fire('change');
    await settle();
    assert.equal(storage.get('vinylpi.logs.level'), 'all');
    assert.equal(visibleEntries(els), 2, 'all includes debug');
    els.logsLevel.value = 'debug';
    await els.logsLevel.fire('change');
    await settle();
    assert.equal(visibleEntries(els), 1, 'debug shows only debug messages');
    els.logsLevel.value = 'all';
    await els.logsLevel.fire('change');
    await settle();
    await els.logsClear.fire('click');
    await settle();
    assert.equal(cutoff, 2);
    assert.equal(visibleEntries(els), 0);
    assert.equal(events.length, 2, 'clear does not delete stored rows');

    // Simulated browser refresh: same SQLite backend and localStorage, new page JS.
    els = buildBrowser();
    await settle();
    assert.equal(els.logsLevel.value, 'all', 'filter survives refresh');
    assert.equal(visibleEntries(els), 0, 'clear survives refresh');
    await els.logsHistory.fire('click');
    await settle();
    assert.equal(visibleEntries(els), 2, 'history can restore cleared entries');
    await els.logsHistory.fire('click');
    await settle();
    assert.equal(visibleEntries(els), 0, 'hide history restores cleared view');
    events.push({id:3, timestamp:1792750200, level:'ERROR', source:'Test', message:'New error'});
    els = buildBrowser();
    await settle();
    assert.equal(visibleEntries(els), 1, 'new messages remain visible');
    console.log('Logs UI: filter persistence, clear persistence, history, and new events passed');
})().catch(e => {console.error(e); process.exitCode=1});
