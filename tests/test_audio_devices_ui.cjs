/* Audio Settings should show physical inputs rather than all ALSA aliases. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/static/js/pages/settings.js'), 'utf8');
const audioCode = source.split('// The Pixoo is not probed')[0];
assert.ok(audioCode.includes('function audioDeviceOptions('), 'audio option builder must be available');

const nodes = {
    audioDeviceStatus: { textContent: '', hidden: true },
    audioDeviceDetails: { textContent: '' },
    audioDeviceAdvanced: { checked: false },
    refreshAudioDevices: { disabled: false },
};
const select = {
    options: [],
    _value: '',
    replaceChildren() { this.options = []; this._value = ''; },
    appendChild(option) { this.options.push(option); },
    set value(value) { this._value = this.options.some(x => x.value === value) ? value : ''; },
    get value() { return this._value; },
};
nodes.audioDeviceName = select;
const document = {
    getElementById(id) { return nodes[id] || null; },
    createElement(tag) {
        assert.equal(tag, 'option');
        return { value: '', textContent: '', dataset: {} };
    },
};
const context = { document, console, fetch: async () => ({ ok: true, json: async () => ({ ok: true, devices }) }) };
vm.createContext(context);
vm.runInContext(audioCode, context);

const devices = [
    { name: 'null', label: 'Discard all samples (playback) or generate zero samples (capture)' },
    { name: 'default', label: 'Default Audio Device · ALSA' },
    { name: 'sysdefault', label: 'Default Audio Device · ALSA' },
    { name: 'hw:CARD=CODEC,DEV=0', label: 'USB AUDIO CODEC, USB Audio Direct hardware device without any conversions' },
    { name: 'plughw:CARD=CODEC,DEV=0', label: 'USB AUDIO CODEC, USB Audio Hardware device with all software conversions' },
    { name: 'default:CARD=CODEC', label: 'USB AUDIO CODEC, USB Audio Default Audio Device · ALSA' },
    { name: 'sysdefault:CARD=CODEC', label: 'USB AUDIO CODEC, USB Audio Default Audio Device · ALSA' },
    { name: 'front:CARD=CODEC,DEV=0', label: 'USB AUDIO CODEC, USB Audio Front output / input' },
    { name: 'dsnoop:CARD=CODEC,DEV=0', label: 'USB AUDIO CODEC, USB Audio Direct sample snooping device' },
];

function populate(configured = '') {
    context.populateAudioDeviceSelect(devices, configured);
    return select.options;
}
let options = populate();
assert.deepEqual(options.map(x => x.value), ['', 'plughw:CARD=CODEC,DEV=0']);
assert.match(options[1].textContent, /USB Audio CODEC.*Recommended/);
assert.ok(!options.some(x => x.value === 'null'));
assert.match(nodes.audioDeviceDetails.textContent, /Automatic prioritizes USB/);

options = populate('USB AUDIO  CODEC: Audio (hw:0,0)');
assert.equal(select.value, 'plughw:CARD=CODEC,DEV=0', 'legacy Python label should select preferred ALSA path');
assert.match(nodes.audioDeviceStatus.textContent, /Previous Python audio input matched/);

options = populate('default:CARD=CODEC');
assert.equal(select.value, 'default:CARD=CODEC', 'saved advanced selection must not be silently modified');
assert.ok(options.some(x => x.value === 'default:CARD=CODEC'));
assert.match(nodes.audioDeviceDetails.textContent, /ALSA default/);

nodes.audioDeviceAdvanced.checked = true;
options = populate('default:CARD=CODEC');
assert.ok(options.some(x => x.value === 'hw:CARD=CODEC,DEV=0'), 'advanced should expose direct hardware path');
assert.ok(options.some(x => x.value === 'sysdefault:CARD=CODEC'), 'advanced should expose standard aliases');
assert.ok(!options.some(x => x.value === 'null'), 'never offer a silent null input');
assert.equal(select.value, 'default:CARD=CODEC');

nodes.audioDeviceAdvanced.checked = false;
options = populate('plughw:CARD=CODEC,DEV=0');
assert.equal(options.length, 2, 'advanced paths must disappear without erasing selected preferred input');
assert.equal(select.value, 'plughw:CARD=CODEC,DEV=0');
assert.match(nodes.audioDeviceDetails.textContent, /Format conversion/);

options = populate('unavailable-device');
assert.equal(select.value, 'unavailable-device', 'unavailable saved input must remain visible for correction');
assert.match(options[options.length - 1].textContent, /Not available/);

// Multiple real USB cards must remain independently selectable.
const multi = devices.concat([
    { name: 'plughw:CARD=MIC,DEV=0', label: 'USB Microphone, USB Audio' },
    { name: 'hw:CARD=MIC,DEV=0', label: 'USB Microphone, USB Audio direct' },
]);
const result = context.audioDeviceOptions(multi, '', false);
assert.deepEqual(Array.from(result.options, x => x.value), ['', 'plughw:CARD=CODEC,DEV=0', 'plughw:CARD=MIC,DEV=0']);

// Refresh should preserve the chosen technical value and its availability.
(async () => {
    nodes.audioDeviceAdvanced.checked = true;
    populate('hw:CARD=CODEC,DEV=0');
    await context.loadAudioDevices(null);
    assert.equal(select.value, 'hw:CARD=CODEC,DEV=0');
    assert.equal(nodes.refreshAudioDevices.disabled, false);
    console.log('Audio device settings tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
