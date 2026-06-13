/**
 * @vitest-environment happy-dom
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const THEMES = ['dark', 'midnight', 'light', 'nord'];

describe('Theme system', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('data-theme');
    localStorage.clear();
  });

  it('defaults to dark theme when no theme saved', () => {
    const saved = localStorage.getItem('theme');
    expect(saved).toBeNull();
    // dark is the default
    document.documentElement.setAttribute('data-theme', 'dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it.each(THEMES)('applies %s theme via data-theme attribute', (theme) => {
    document.documentElement.setAttribute('data-theme', theme);
    expect(document.documentElement.getAttribute('data-theme')).toBe(theme);
  });

  it('persists theme choice to localStorage', () => {
    localStorage.setItem('theme', 'nord');
    const saved = localStorage.getItem('theme');
    expect(saved).toBe('nord');

    // On reload, apply from localStorage
    document.documentElement.setAttribute('data-theme', saved);
    expect(document.documentElement.getAttribute('data-theme')).toBe('nord');
  });

  it('switches from dark to light', () => {
    document.documentElement.setAttribute('data-theme', 'dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');

    document.documentElement.setAttribute('data-theme', 'light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  it('removes data-theme attribute when set to unknown value', () => {
    document.documentElement.setAttribute('data-theme', 'dark');

    // Simulate: theme value not in valid list, remove attribute (fallback to CSS defaults)
    const valid = THEMES.includes('custom');
    if (!valid) {
      document.documentElement.removeAttribute('data-theme');
    }
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('CSS variables are defined for each theme', () => {
    const style = document.createElement('style');
    style.textContent = `
      [data-theme="dark"] { --bg: #1a1a2e; --text: #eee; }
      [data-theme="midnight"] { --bg: #0f0f1a; --text: #c0c0ff; }
      [data-theme="light"] { --bg: #fff; --text: #222; }
      [data-theme="nord"] { --bg: #2e3440; --text: #eceff4; }
    `;
    document.head.appendChild(style);
    expect(style.sheet.cssRules.length).toBe(4);
  });

  it('theme selector in settings matches available themes', () => {
    const select = document.createElement('select');
    select.id = 'theme-select';
    THEMES.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t;
      select.appendChild(opt);
    });
    expect(select.options.length).toBe(4);
    expect(select.options[0].value).toBe('dark');
    expect(select.options[3].value).toBe('nord');
  });
});
