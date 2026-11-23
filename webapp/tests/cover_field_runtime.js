// Executes the rendered component with a small DOM model, without browser packages.
const fs = require('node:fs');
const vm = require('node:vm');
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
const urls = new Map();
const revoked = [];
const all = [];

class Element {
  constructor(node) {
    this.tagName = node.tag;
    this.attributes = node.attrs;
    this.text = node.text;
    this.children = node.children.map(child => new Element(child));
    this.listeners = {};
    this.hidden = 'hidden' in this.attributes;
    this.checked = 'checked' in this.attributes;
    this.files = [];
    this.value = '';
    const classes = new Set((this.attributes.class || '').split(' '));
    this.classList = { remove: name => classes.delete(name), contains: name => classes.has(name) };
    all.push(this);
  }
  get textContent() { return this.text; }
  set textContent(value) { this.text = value; }
  get src() { return this.attributes.src; }
  set src(value) { this.attributes.src = value; }
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

async function main() {
  const roots = request.components.map(component => new Element(component));
  const context = {
    document: { getElementById: id => all.find(element => element.attributes.id === id) },
    URL: {
      createObjectURL(file) {
        const url = 'blob:' + (urls.size + 1);
        urls.set(url, file);
        return url;
      },
      revokeObjectURL(url) { revoked.push(url); },
    },
  };
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
    }
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
    };
  });
  process.stdout.write(JSON.stringify({ components: result, revoked }));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
