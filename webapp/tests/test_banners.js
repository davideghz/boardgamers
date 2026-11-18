const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(__dirname, '../templates/partials/_banners.html'), 'utf8');
const script = template.match(/<script>([\s\S]*?)<\/script>/)[1];
const keyFor = (key = 'first', version = 1, scope = 'browser') => `bg:banner:${key}:v${version}:${scope}`;

function load({items = [{key: 'first'}], local = new Map(), session = new Map(),
               readError = false, writeError = false, clock = {now: 1805500000000}} = {}) {
  const events = {};
  const banners = items.map(item => {
    const handlers = {};
    return {
      hidden: true, handlers,
      dataset: {bannerKey: item.key, bannerVersion: String(item.version ?? 1),
        bannerPolicy: item.policy ?? 'permanent', bannerDays: String(item.days ?? ''),
        bannerScope: item.scope ?? 'browser'},
      querySelector: selector => {
        assert.equal(selector, '[data-banner-close]');
        return {addEventListener: (name, fn) => {handlers[name] = fn;}};
      },
    };
  });
  const storage = map => ({
    getItem: key => {if (readError) throw Error('Storage unavailable'); return map.get(key) ?? null;},
    setItem: (key, value) => {if (writeError) throw Error('Storage full'); map.set(key, value);},
  });
  vm.runInNewContext(script, {
    document: {getElementById: id => {
      assert.equal(id, 'site-banners');
      return {querySelectorAll: selector => {assert.equal(selector, '[data-banner]'); return banners;}};
    }},
    window: {addEventListener: (name, fn) => {events[name] = fn;}},
    localStorage: storage(local), sessionStorage: storage(session), Date: {now: () => clock.now},
  });
  return {banners, local, session, events, clock, close: (i = 0) => banners[i].handlers.click()};
}

test('shows only the highest priority available banner', () => {
  const page = load({items: [{key: 'first'}, {key: 'second'}]});
  assert.equal(page.banners[0].hidden, false);
  assert.equal(page.banners[1].hidden, true);
  page.close();
  assert.equal(page.banners[0].hidden, true);
  assert.equal(page.banners[1].hidden, true, 'Do not replace the banner immediately');
  const next = load({items: [{key: 'first'}, {key: 'second'}], local: page.local});
  assert.equal(next.banners[0].hidden, true);
  assert.equal(next.banners[1].hidden, false);
});

test('permanent closing survives later visits without an expiry', () => {
  const page = load();
  page.close();
  page.clock.now += 365 * 24 * 3600000;
  assert.equal(load({local: page.local, clock: page.clock}).banners[0].hidden, true);
});

test('a new version is independent of an old dismissal', () => {
  const page = load();
  page.close();
  assert.equal(load({items: [{key: 'first', version: 2}], local: page.local}).banners[0].hidden, false);
});

test('temporary closing expires after the configured number of days', () => {
  const items = [{key: 'first', policy: 'days', days: 3}];
  const page = load({items});
  page.close();
  const options = {items, local: page.local, clock: page.clock};
  page.clock.now += 2 * 24 * 3600000;
  assert.equal(load(options).banners[0].hidden, true);
  page.clock.now += 24 * 3600000;
  assert.equal(load(options).banners[0].hidden, false);
});

test('session closing affects only that tab session', () => {
  const items = [{key: 'first', policy: 'session'}];
  const page = load({items});
  page.close();
  assert.equal(page.local.size, 0);
  assert.equal(load({items, session: page.session}).banners[0].hidden, true);
  assert.equal(load({items, local: page.local}).banners[0].hidden, false);
});

test('account-specific closing is separate for different users', () => {
  const page = load({items: [{key: 'first', scope: 'user:1'}]});
  page.close();
  assert.equal(load({items: [{key: 'first', scope: 'user:1'}], local: page.local}).banners[0].hidden, true);
  assert.equal(load({items: [{key: 'first', scope: 'user:2'}], local: page.local}).banners[0].hidden, false);
});

test('the banner closes immediately even if saving fails', () => {
  const page = load({writeError: true});
  assert.equal(page.banners[0].hidden, false);
  page.close();
  assert.equal(page.banners[0].hidden, true);
});

test('unreadable storage keeps the promotional banner hidden', () => {
  assert.equal(load({readError: true}).banners[0].hidden, true);
});

test('corrupted records are ignored without stopping other candidates', () => {
  for (const raw of ['bad json', 'null', '{}', '{"dismissedAt":"bad","expiresAt":null}']) {
    assert.equal(load({local: new Map([[keyFor(), raw]])}).banners[0].hidden, false);
  }
});

test('migrates legacy contributor dismissals without the 24 hour expiry', () => {
  for (const local of [new Map([['alertClosedTimestamp', '1000']]),
                       new Map([['bg:contributor-banner:dismissed', '1']])]) {
    const page = load({items: [{key: 'contributor-invite'}], local});
    assert.equal(page.banners[0].hidden, true);
    assert.ok(local.has(keyFor('contributor-invite')));
    assert.equal(load({items: [{key: 'contributor-invite', version: 2}], local}).banners[0].hidden, false);
  }
});

test('a dismissal in another tab hides the active banner', () => {
  const page = load();
  page.local.set(keyFor(), JSON.stringify({dismissedAt: page.clock.now, expiresAt: null}));
  page.events.storage({key: keyFor()});
  assert.equal(page.banners[0].hidden, true);
});

test('returning through browser history rechecks saved dismissals', () => {
  const page = load();
  page.local.set(keyFor(), JSON.stringify({dismissedAt: page.clock.now, expiresAt: null}));
  page.events.pageshow({persisted: true});
  assert.equal(page.banners[0].hidden, true);
});
