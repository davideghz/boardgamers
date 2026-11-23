// Executes the rendered component with a small DOM model, without browser packages.
const fs = require('node:fs');
const vm = require('node:vm');
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
const urls = new Map();
const revoked = [];
const all = [];
const cropperSessions = [];
const croppedImages = [];
const observers = [];
let scriptsLoaded = 0;

class Element {
  constructor(node) {
    this.tagName = node.tag;
    this.attributes = node.attrs;
    this.text = node.text;
    this.children = node.children.map(child => new Element(child));
    this.listeners = {};
    this.hidden = 'hidden' in this.attributes;
    this.checked = 'checked' in this.attributes;
    this.disabled = 'disabled' in this.attributes;
    this.files = [];
    this.value = '';
    const classes = new Set((this.attributes.class || '').split(' '));
    this.classList = {
      add: name => classes.add(name),
      remove: name => classes.delete(name),
      contains: name => classes.has(name),
    };
    all.push(this);
  }
  get dataset() {
    return { cropMaxSide: this.attributes['data-crop-max-side'] };
  }
  get content() { return this; }
  get innerHTML() { return ''; }
  getBoundingClientRect() { return this.rect || { width: 600, height: 400 }; }
  decode() { return Promise.resolve(this); }
  showModal() { this.open = true; }
  close() { this.open = false; }
  get value() { return this.inputValue; }
  set value(value) {
    this.inputValue = value;
    if (value === '' && this.tagName === 'input') this.files = [];
  }
  get textContent() { return this.text; }
  set textContent(value) { this.text = value; }
  get src() { return this.attributes.src; }
  set src(value) { this.attributes.src = value; this.dispatch('load'); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(event, callback) {
    (this.listeners[event] ||= []).push(callback);
  }
  async dispatch(event) {
    for (const callback of this.listeners[event] || []) await callback({ preventDefault() {} });
  }
  querySelector(selector) {
    for (const child of this.children) {
      if (child.matches(selector)) return child;
      const match = child.querySelector(selector);
      if (match) return match;
    }
    return null;
  }
  matches(selector) {
    if (selector === 'input[type="file"]') return this.tagName === 'input' && this.attributes.type === 'file';
    if (selector.startsWith('[')) return selector.slice(1, -1) in this.attributes;
    return this.tagName === selector;
  }
}

class Cropper {
  constructor(image, options) {
    this.container = options.container;
    this.canvas = { disabled: false, getBoundingClientRect: () => this.container.getBoundingClientRect() };
    this.selection = new Element({ tag: 'cropper-selection', attrs: {}, text: '', children: [] });
    this.selection.$change = (x, y, width, height) => {
      // Cropper keeps the selection inside the canvas area allowed by minInset.
      const [top, left] = this.selection.minInset.split(' ').map(parseFloat);
      const bounds = this.canvas.getBoundingClientRect();
      if (width > bounds.width - 2 * left || height > bounds.height - 2 * top) return;
      Object.assign(this.selection, { x, y, width, height });
    };
    this.selection.$toCanvas = async ({ width, height }) => {
      croppedImages.push({ component: this.container.component, width, height });
      return { toBlob: (callback, type) => callback({ type, width, height }) };
    };
    this.image = { $ready: async () => {}, $setTransform() {} };
    cropperSessions.push(this);
  }
  getCropperCanvas() { return this.canvas; }
  getCropperSelection() { return this.selection; }
  getCropperImage() { return this.image; }
  destroy() {}
}

async function main() {
  const roots = request.components.map(component => new Element(component));
  const window = {};
  const context = {
    window,
    Image: class {
      constructor() { this.naturalWidth = 1600; this.naturalHeight = 900; }
      decode() { return Promise.resolve(this); }
    },
    File: class {
      constructor(parts, name, options) { Object.assign(this, parts[0], options, { name }); }
    },
    DataTransfer: class {
      constructor() {
        this.files = [];
        this.items = { add: file => this.files.push(file) };
      }
    },
    ResizeObserver: class {
      constructor(callback) { this.callback = callback; observers.push(this); }
      observe(element) { this.element = element; }
      disconnect() { this.disconnected = true; }
    },
    document: {
      getElementById: id => all.find(element => element.attributes.id === id),
      createElement: tag => new Element({ tag, attrs: {}, text: '', children: [] }),
      head: { append(script) {
        scriptsLoaded += 1;
        window.Cropper = { Cropper };
        script.onload();
      } },
    },
    URL: {
      createObjectURL(file) {
        const url = 'blob:' + (urls.size + 1);
        urls.set(url, file);
        return url;
      },
      revokeObjectURL(url) { revoked.push(url); },
    },
  };
  if (request.disableCrop) context.DataTransfer = undefined;
  for (let index = 0; index < roots.length; index += 1) {
    const stage = roots[index].querySelector('[data-cover-crop-stage]');
    if (stage) stage.component = index;
  }
  for (const script of all.filter(element => element.tagName === 'script')) {
    vm.runInNewContext(script.textContent, context);
  }
  for (const action of request.actions) {
    const root = roots[action.component].querySelector('[data-cover-field]');
    const input = root.querySelector('input[type="file"]');
    if (action.type === 'select') {
      input.files = [{ name: action.filename }];
      await input.dispatch('change');
    } else if (action.type === 'clear') {
      const clear = root.querySelector('[data-cover-clear]');
      clear.checked = action.checked;
      await clear.dispatch('change');
    } else if (action.type === 'resize') {
      const stage = root.querySelector('[data-cover-crop-stage]');
      stage.rect = { width: action.width, height: action.height };
      for (const observer of observers) {
        if (observer.element === stage && !observer.disconnected) observer.callback();
      }
    } else {
      await root.querySelector('[data-cover-' + action.type + ']').dispatch('click');
    }
    await new Promise(resolve => setImmediate(resolve));
  }
  const result = roots.map(container => {
    const root = container.querySelector('[data-cover-field]');
    const image = root.querySelector('[data-cover-image]');
    const preview = root.querySelector('[data-cover-preview]');
    const clear = root.querySelector('[data-cover-clear]');
    return {
      filename: root.querySelector('[data-cover-filename]').textContent.trim(),
      src: image?.src,
      hidden: image?.hidden,
      previewHidden: preview?.classList.contains('hidden'),
      checked: clear?.checked,
      dialogOpen: root.querySelector('[data-cover-dialog]')?.open || false,
      uploads: root.querySelector('input[type="file"]').files.map(file => ({
        name: file.name, width: file.width, height: file.height,
      })),
    };
  });
  process.stdout.write(JSON.stringify({ components: result, revoked, exports: croppedImages, scriptsLoaded }));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
