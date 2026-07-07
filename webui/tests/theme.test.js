/**
 * @vitest-environment happy-dom
 *
 * Real tests for the theme/appearance and focus-trap utilities in
 * webui/js/modules/utils.js: applyTheme, applyAccentColor,
 * detectGPUCapability, and trapFocus.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { installMinimalDOM } from './_dom-shim.js';

// Only install the offline DOM shim if a real DOM isn't already present —
// real vitest + happy-dom (after `npm install`) provides document/window
// itself, and this must not clobber it.
if (typeof document === 'undefined') installMinimalDOM();
const { applyTheme, applyAccentColor, detectGPUCapability, trapFocus } =
  await import('../js/modules/utils.js');

beforeEach(() => {
  document.documentElement.removeAttribute('data-theme');
  document.body.innerHTML = '';
});

describe('applyTheme', () => {
  it('dark theme removes the data-theme attribute (dark is the CSS default, no attribute needed)', () => {
    document.documentElement.setAttribute('data-theme', 'light');
    applyTheme('dark');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('non-dark themes set data-theme to the given value', () => {
    for (const theme of ['midnight', 'light', 'nord']) {
      applyTheme(theme);
      expect(document.documentElement.getAttribute('data-theme')).toBe(theme);
    }
  });

  it('switching from a non-dark theme back to dark removes the attribute again', () => {
    applyTheme('nord');
    expect(document.documentElement.getAttribute('data-theme')).toBe('nord');
    applyTheme('dark');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });
});

describe('applyAccentColor', () => {
  it('sets the --accent CSS variable to the given hex value', () => {
    applyAccentColor('#6c5ce7');
    expect(document.documentElement.style['--accent']).toBe('#6c5ce7');
  });

  it('computes --accent-dim as a 15%-alpha rgba() of the same color', () => {
    applyAccentColor('#ff0000');
    expect(document.documentElement.style['--accent-dim']).toBe('rgba(255, 0, 0, 0.15)');
  });

  it('marks the matching swatch active and unmarks the others', () => {
    const wrap = document.createElement('div');
    wrap.id = 'color-swatches';
    const s1 = document.createElement('span');
    s1.className = 'swatch';
    s1.dataset.color = '#6c5ce7';
    const s2 = document.createElement('span');
    s2.className = 'swatch';
    s2.dataset.color = '#00b894';
    wrap.appendChild(s1);
    wrap.appendChild(s2);
    document.body.appendChild(wrap);

    applyAccentColor('#00b894');
    expect(s1.classList.contains('active')).toBe(false);
    expect(s2.classList.contains('active')).toBe(true);
  });

  it('syncs the accent color picker input value when present', () => {
    const picker = document.createElement('input');
    picker.id = 'accent-color-picker';
    document.body.appendChild(picker);
    applyAccentColor('#123456');
    expect(picker.value).toBe('#123456');
  });

  it('does not throw when there is no picker or swatches in the DOM', () => {
    expect(() => applyAccentColor('#abcdef')).not.toThrow();
  });
});

describe('detectGPUCapability', () => {
  it('returns the software tier when WebGL is unavailable', () => {
    const result = detectGPUCapability();
    expect(result.tier).toBe('software');
    expect(result.reason).toBe('no-webgl');
  });

  it('flags a known low-end renderer string as the low tier', () => {
    const fakeGl = {
      getExtension: () => ({ UNMASKED_RENDERER_WEBGL: 1, UNMASKED_VENDOR_WEBGL: 2 }),
      getParameter: (p) => (p === 1 ? 'Mali-450 MP' : p === 2 ? 'ARM' : 8192),
      MAX_TEXTURE_SIZE: 'MAX_TEXTURE_SIZE',
    };
    const origCreateElement = document.createElement.bind(document);
    document.createElement = (tag) => {
      const el = origCreateElement(tag);
      if (tag === 'canvas') el.getContext = () => fakeGl;
      return el;
    };
    const result = detectGPUCapability();
    expect(result.tier).toBe('low');
    document.createElement = origCreateElement;
  });

  it('flags a very small max texture size as the low tier even on a normal-sounding renderer', () => {
    const fakeGl = {
      getExtension: () => null,
      getParameter: (p) => (p === 'MAX_TEXTURE_SIZE' ? 2048 : ''),
      MAX_TEXTURE_SIZE: 'MAX_TEXTURE_SIZE',
    };
    const origCreateElement = document.createElement.bind(document);
    document.createElement = (tag) => {
      const el = origCreateElement(tag);
      if (tag === 'canvas') el.getContext = () => fakeGl;
      return el;
    };
    expect(detectGPUCapability().tier).toBe('low');
    document.createElement = origCreateElement;
  });

  it('reports the medium tier for a capable but mobile renderer', () => {
    const fakeGl = {
      getExtension: () => null,
      getParameter: () => 8192,
      MAX_TEXTURE_SIZE: 'MAX_TEXTURE_SIZE',
    };
    const origCreateElement = document.createElement.bind(document);
    const origNavigator = global.navigator;
    document.createElement = (tag) => {
      const el = origCreateElement(tag);
      if (tag === 'canvas') el.getContext = () => fakeGl;
      return el;
    };
    Object.defineProperty(global, 'navigator', { value: { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)' }, configurable: true });
    expect(detectGPUCapability().tier).toBe('medium');
    document.createElement = origCreateElement;
    Object.defineProperty(global, 'navigator', { value: origNavigator, configurable: true });
  });

  it('reports the high tier for a capable desktop renderer', () => {
    const fakeGl = {
      getExtension: () => null,
      getParameter: () => 16384,
      MAX_TEXTURE_SIZE: 'MAX_TEXTURE_SIZE',
    };
    const origCreateElement = document.createElement.bind(document);
    const origNavigator = global.navigator;
    document.createElement = (tag) => {
      const el = origCreateElement(tag);
      if (tag === 'canvas') el.getContext = () => fakeGl;
      return el;
    };
    Object.defineProperty(global, 'navigator', { value: { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' }, configurable: true });
    expect(detectGPUCapability().tier).toBe('high');
    document.createElement = origCreateElement;
    Object.defineProperty(global, 'navigator', { value: origNavigator, configurable: true });
  });
});

describe('trapFocus', () => {
  function makeModal() {
    const modal = document.createElement('div');
    const btn1 = document.createElement('button');
    const input = document.createElement('input');
    const btn2 = document.createElement('button');
    modal.appendChild(btn1);
    modal.appendChild(input);
    modal.appendChild(btn2);
    document.body.appendChild(modal);
    return { modal, btn1, input, btn2 };
  }

  it('does nothing (no throw) when given a null element', () => {
    expect(() => trapFocus(null)).not.toThrow();
  });

  it('Tab on the last focusable element wraps focus to the first', () => {
    const { modal, btn1, btn2 } = makeModal();
    trapFocus(modal);
    btn2.focus();
    let prevented = false;
    modal.dispatchEvent({ type: 'keydown', key: 'Tab', shiftKey: false, preventDefault: () => { prevented = true; } });
    expect(prevented).toBe(true);
    expect(document.activeElement).toBe(btn1);
  });

  it('Shift+Tab on the first focusable element wraps focus to the last', () => {
    const { modal, btn1, btn2 } = makeModal();
    trapFocus(modal);
    btn1.focus();
    let prevented = false;
    modal.dispatchEvent({ type: 'keydown', key: 'Tab', shiftKey: true, preventDefault: () => { prevented = true; } });
    expect(prevented).toBe(true);
    expect(document.activeElement).toBe(btn2);
  });

  it('Tab on a middle element does not get intercepted', () => {
    const { modal, input } = makeModal();
    trapFocus(modal);
    input.focus();
    let prevented = false;
    modal.dispatchEvent({ type: 'keydown', key: 'Tab', shiftKey: false, preventDefault: () => { prevented = true; } });
    expect(prevented).toBe(false);
  });

  it('non-Tab keys are ignored entirely', () => {
    const { modal, btn2 } = makeModal();
    trapFocus(modal);
    btn2.focus();
    let prevented = false;
    modal.dispatchEvent({ type: 'keydown', key: 'Enter', shiftKey: false, preventDefault: () => { prevented = true; } });
    expect(prevented).toBe(false);
  });

  it('auto-focuses the first focusable element shortly after being called', () => {
    vi.useFakeTimers();
    const { modal, btn1 } = makeModal();
    trapFocus(modal);
    vi.advanceTimersByTime(50);
    expect(document.activeElement).toBe(btn1);
    vi.useRealTimers();
  });
});
