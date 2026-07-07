/**
 * @vitest-environment happy-dom
 *
 * Real tests for i18n.js and custom-select.js. (audio-utils.js is already
 * covered thoroughly in lipsync.test.js and isn't duplicated here.)
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { installMinimalDOM } from './_dom-shim.js';

// Only install the offline DOM shim if a real DOM isn't already present —
// real vitest + happy-dom (after `npm install`) provides document/window
// itself, and this must not clobber it.
if (typeof document === 'undefined') installMinimalDOM();

describe('i18n.js', () => {
  let i18n;
  beforeEach(async () => {
    vi.resetModules?.();
    document.documentElement.lang = '';
    document.body.innerHTML = '';
    global.fetch = async (url) => {
      if (url.includes('zh')) {
        return { ok: true, json: async () => ({ greeting: '你好 {name}' }) };
      }
      return { ok: true, json: async () => ({ greeting: 'Hello {name}', untouched: 'stays' }) };
    };
    // Re-import fresh each time since the module keeps internal state
    // (_current/_lang/_cache) at module scope.
    i18n = await import(`../js/i18n.js?t=${Math.random()}`);
  });

  it('t() returns the key itself when no translation is loaded yet', () => {
    expect(i18n.t('greeting')).toBe('greeting');
  });

  it('setLanguage loads translations and t() reflects them afterward', async () => {
    await i18n.setLanguage('en');
    expect(i18n.t('greeting', { name: 'Ana' })).toBe('Hello Ana');
  });

  it('t() substitutes every {param} occurrence, repeated or not', async () => {
    global.fetch = async () => ({ ok: true, json: async () => ({ repeat: '{x}-{x}-{x}' }) });
    await i18n.setLanguage('en');
    expect(i18n.t('repeat', { x: 'A' })).toBe('A-A-A');
  });

  it('getCurrentLang reflects the last language set', async () => {
    await i18n.setLanguage('zh');
    expect(i18n.getCurrentLang()).toBe('zh');
  });

  it('falls back to an empty translation set (and does not throw) when the fetch fails', async () => {
    global.fetch = async () => ({ ok: false, status: 404 });
    await i18n.setLanguage('en');
    expect(i18n.t('greeting')).toBe('greeting'); // untranslated key falls back to itself
  });

  it('applyTranslations sets textContent for [data-i18n] elements', async () => {
    const el = document.createElement('span');
    el.setAttribute('data-i18n', 'greeting');
    document.body.appendChild(el);
    await i18n.setLanguage('en');
    expect(el.textContent).toBe('Hello {name}'); // no params passed via data-i18n path
  });

  it('applyTranslations sets placeholder for [data-i18n-placeholder] elements', async () => {
    const el = document.createElement('input');
    el.setAttribute('data-i18n-placeholder', 'greeting');
    document.body.appendChild(el);
    await i18n.setLanguage('en');
    expect(el.placeholder).toBe('Hello {name}');
  });

  it('applyTranslations sets title for [data-i18n-title] elements', async () => {
    const el = document.createElement('div');
    el.setAttribute('data-i18n-title', 'greeting');
    document.body.appendChild(el);
    await i18n.setLanguage('en');
    expect(el.title).toBe('Hello {name}');
  });

  it('applyTranslations sets documentElement.lang to the active language', async () => {
    await i18n.setLanguage('zh');
    expect(document.documentElement.lang).toBe('zh');
  });

  it('initI18n uses the saved language when provided, skipping detection', async () => {
    await i18n.initI18n('zh');
    expect(i18n.getCurrentLang()).toBe('zh');
  });

  it('caches a loaded locale so a second setLanguage call does not re-fetch', async () => {
    let fetchCount = 0;
    global.fetch = async () => {
      fetchCount++;
      return { ok: true, json: async () => ({ greeting: 'Hi' }) };
    };
    await i18n.setLanguage('en');
    await i18n.setLanguage('en');
    expect(fetchCount).toBe(1);
  });
});

describe('custom-select.js', () => {
  let initCustomSelects, syncCustomSelect, syncAllCustomSelects;

  beforeEach(async () => {
    document.body.innerHTML = '';
    const mod = await import(`../js/custom-select.js?t=${Math.random()}`);
    ({ initCustomSelects, syncCustomSelect, syncAllCustomSelects } = mod);
  });

  function makeSelect(options, selectedIndex = 0) {
    const sel = document.createElement('select');
    for (const [value, text] of options) {
      const opt = document.createElement('option');
      opt.setAttribute('value', value);
      opt.textContent = text;
      sel.appendChild(opt);
    }
    sel.selectedIndex = selectedIndex;
    const wrapper = document.createElement('div');
    wrapper.appendChild(sel);
    document.body.appendChild(wrapper);
    return sel;
  }

  it('wraps a <select> in a .custom-select container and hides the original', () => {
    const sel = makeSelect([['a', 'Alpha'], ['b', 'Beta']]);
    initCustomSelects();
    expect(sel.style.display).toBe('none');
    expect(sel.parentNode.querySelector('.custom-select')).not.toBeNull();
  });

  it('the button label shows the currently selected option text', () => {
    const sel = makeSelect([['a', 'Alpha'], ['b', 'Beta']], 1);
    initCustomSelects();
    const btn = sel.parentNode.querySelector('.custom-select-btn');
    expect(btn.textContent).toBe('Beta');
  });

  it('does not double-wrap a select that already has data-custom set', () => {
    const sel = makeSelect([['a', 'Alpha']]);
    initCustomSelects();
    const firstWrapperCount = document.querySelectorAll('.custom-select').length;
    initCustomSelects();
    expect(document.querySelectorAll('.custom-select').length).toBe(firstWrapperCount);
  });

  it('clicking the toggle button opens the dropdown list', () => {
    const sel = makeSelect([['a', 'Alpha'], ['b', 'Beta']]);
    initCustomSelects();
    const wrapper = sel.parentNode.querySelector('.custom-select');
    const btn = wrapper.querySelector('.custom-select-btn');
    btn.click();
    expect(wrapper.classList.contains('open')).toBe(true);
  });

  it('clicking an option updates the real select, the button label, and fires change', () => {
    const sel = makeSelect([['a', 'Alpha'], ['b', 'Beta']], 0);
    let changeFired = false;
    sel.addEventListener('change', () => { changeFired = true; });
    initCustomSelects();
    const wrapper = sel.parentNode.querySelector('.custom-select');
    wrapper.querySelector('.custom-select-btn').click(); // open it (builds the option items)
    const items = wrapper.querySelectorAll('.custom-select-item');
    items[1].click(); // pick "Beta"
    expect(sel.selectedIndex).toBe(1);
    expect(wrapper.querySelector('.custom-select-btn').textContent).toBe('Beta');
    expect(changeFired).toBe(true);
    expect(wrapper.classList.contains('open')).toBe(false); // closes after picking
  });

  it('handles a select with zero options without throwing', () => {
    const sel = makeSelect([]);
    expect(() => initCustomSelects()).not.toThrow();
    const btn = sel.parentNode.querySelector('.custom-select-btn');
    expect(btn.textContent).toBe('Select...');
  });

  it('Escape key closes an open dropdown', () => {
    const sel = makeSelect([['a', 'Alpha'], ['b', 'Beta']]);
    initCustomSelects();
    const wrapper = sel.parentNode.querySelector('.custom-select');
    wrapper.querySelector('.custom-select-btn').click();
    expect(wrapper.classList.contains('open')).toBe(true);
    wrapper.dispatchEvent({ type: 'keydown', key: 'Escape', preventDefault() {} });
    expect(wrapper.classList.contains('open')).toBe(false);
  });

  it('syncCustomSelect updates the button label after the real select changes elsewhere', () => {
    const sel = makeSelect([['a', 'Alpha'], ['b', 'Beta']], 0);
    initCustomSelects();
    sel.selectedIndex = 1; // changed programmatically, not via the dropdown UI
    syncCustomSelect(sel);
    expect(sel.parentNode.querySelector('.custom-select-btn').textContent).toBe('Beta');
  });

  it('syncAllCustomSelects updates every wrapped select on the page', () => {
    const sel1 = makeSelect([['a', 'Alpha'], ['b', 'Beta']], 0);
    const sel2 = makeSelect([['x', 'Xray'], ['y', 'Yankee']], 0);
    initCustomSelects();
    sel1.selectedIndex = 1;
    sel2.selectedIndex = 1;
    syncAllCustomSelects();
    expect(sel1.parentNode.querySelector('.custom-select-btn').textContent).toBe('Beta');
    expect(sel2.parentNode.querySelector('.custom-select-btn').textContent).toBe('Yankee');
  });
});
