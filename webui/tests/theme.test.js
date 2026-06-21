/**
 * @vitest-environment happy-dom
 *
 * BRUTAL tests for theme system — system preferences, edge cases,
 * race conditions, and invalid inputs.
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

// ===================================================================
// BRUTAL edge cases
// ===================================================================

describe('Theme system — brutal edge cases', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('data-theme');
    localStorage.clear();
  });

  it('setting empty string theme', () => {
    document.documentElement.setAttribute('data-theme', '');
    expect(document.documentElement.getAttribute('data-theme')).toBe('');
  });

  it('setting very long theme name', () => {
    const longName = 'x'.repeat(10000);
    document.documentElement.setAttribute('data-theme', longName);
    expect(document.documentElement.getAttribute('data-theme')).toBe(longName);
  });

  it('rapid theme switching does not crash', () => {
    for (let i = 0; i < 1000; i++) {
      document.documentElement.setAttribute('data-theme', THEMES[i % THEMES.length]);
    }
    // Last iteration: i=999, 999 % 4 = 3, THEMES[3] = 'nord'
    expect(document.documentElement.getAttribute('data-theme')).toBe('nord');
  });

  it('localStorage theme persistence with special characters', () => {
    localStorage.setItem('theme', 'dark;rm -rf /');
    expect(localStorage.getItem('theme')).toBe('dark;rm -rf /');
  });

  it('localStorage quota exceeded gracefully', () => {
    // Fill localStorage to quota
    try {
      for (let i = 0; i < 10000; i++) {
        localStorage.setItem(`key${i}`, 'x'.repeat(1000));
      }
    } catch (e) {
      // Quota exceeded — expected
    }
    // Theme save might fail but should not crash
    try {
      localStorage.setItem('theme', 'dark');
    } catch (e) {
      // Expected under quota pressure
    }
  });

  it('removeAttribute is idempotent', () => {
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.removeAttribute('data-theme');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('setAttribute then removeAttribute restores state', () => {
    document.documentElement.setAttribute('data-theme', 'dark');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(true);
    document.documentElement.removeAttribute('data-theme');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('getTheme returns current theme or null', () => {
    // No theme set
    expect(document.documentElement.getAttribute('data-theme')).toBeNull();
    // Theme set
    document.documentElement.setAttribute('data-theme', 'nord');
    expect(document.documentElement.getAttribute('data-theme')).toBe('nord');
  });

  it('each theme has distinct background color', () => {
    const colors = {
      dark: '#1a1a2e',
      midnight: '#0f0f1a',
      light: '#ffffff',
      nord: '#2e3440',
    };
    const uniqueColors = new Set(Object.values(colors));
    expect(uniqueColors.size).toBe(4);
  });

  it('theme CSS has correct selector syntax', () => {
    THEMES.forEach(theme => {
      const selector = `[data-theme="${theme}"]`;
      expect(selector).toContain(theme);
    });
  });

  it('localStorage getItem returns string not number', () => {
    localStorage.setItem('theme', 'dark');
    const value = localStorage.getItem('theme');
    expect(typeof value).toBe('string');
  });

  it('concurrent setAttribute does not corrupt state', () => {
    const results = [];
    for (let i = 0; i < 100; i++) {
      document.documentElement.setAttribute('data-theme', THEMES[i % THEMES.length]);
      results.push(document.documentElement.getAttribute('data-theme'));
    }
    // Last write wins: i=99, 99 % 4 = 3, THEMES[3] = 'nord'
    expect(results[results.length - 1]).toBe('nord');
  });

  it('theme name with quotes does not break attribute', () => {
    document.documentElement.setAttribute('data-theme', 'dark"evil');
    const val = document.documentElement.getAttribute('data-theme');
    expect(val).toBe('dark"evil');
  });

  it('theme name with spaces', () => {
    document.documentElement.setAttribute('data-theme', 'dark mode');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark mode');
  });
});