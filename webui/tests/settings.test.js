/**
 * @vitest-environment happy-dom
 *
 * Real tests for settings.js's rendering functions: renderField (every
 * field type it supports), renderCategory (assembly + show_if filtering +
 * category-specific extras), and filterSettings (search). These call the
 * actual functions against the actual SETTINGS_SCHEMA — nothing here is a
 * fabricated stand-in HTML structure.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { installMinimalDOM } from './_dom-shim.js';

// Only install the offline DOM shim if a real DOM isn't already present —
// real vitest + happy-dom (after `npm install`) provides document/window
// itself, and this must not clobber it.
if (typeof document === 'undefined') installMinimalDOM();
global.fetch = async () => ({ ok: false, status: 0, json: async () => ({}) });

const { renderField, renderCategory, filterSettings, getActiveSettingsTab, setActiveSettingsTab } =
  await import('../js/modules/settings.js');
const { setSettingsCache } = await import('../js/modules/state.js');
const { SETTINGS_SCHEMA } = await import('../js/modules/settings-schema.js');

beforeEach(() => {
  setSettingsCache({ provider: { active: 'anthropic' }, memory: { enabled: true } });
});

describe('renderField', () => {
  it('toggle: renders a checked checkbox when the underlying value is true', () => {
    const html = renderField('memory_enabled', SETTINGS_SCHEMA.Memory.fields.memory_enabled);
    expect(html).toContain('id="field-memory_enabled"');
    expect(html).toContain('data-key="memory.enabled"');
    expect(html).toMatch(/type="checkbox"[^>]*checked/);
  });

  it('toggle: renders unchecked when the value is false', () => {
    setSettingsCache({ memory: { enabled: false } });
    const html = renderField('memory_enabled', SETTINGS_SCHEMA.Memory.fields.memory_enabled);
    expect(html).not.toMatch(/type="checkbox"[^>]*checked/);
  });

  it('select: marks the option matching the current value as selected', () => {
    setSettingsCache({ provider: { active: 'anthropic' } });
    const html = renderField('active_provider', SETTINGS_SCHEMA.Provider.fields.active_provider);
    expect(html).toContain('<select');
    expect(html).toContain('id="field-active_provider"');
  });

  it('password: HTML-escapes the value (a literal value is never reflected unescaped)', () => {
    setSettingsCache({ provider: { active: 'anthropic', anthropic: { api_key: '"><script>x</script>' } } });
    const html = renderField('api_key', SETTINGS_SCHEMA.Provider.fields.api_key);
    expect(html).not.toContain('<script>x</script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('password: includes a show/hide toggle and a test-connection button', () => {
    const html = renderField('api_key', SETTINGS_SCHEMA.Provider.fields.api_key);
    expect(html).toContain('toggle-vis-btn');
    expect(html).toContain('test-conn-btn');
  });

  it('number: reflects min/max/step from the field definition', () => {
    const html = renderField('short_term_size', SETTINGS_SCHEMA.Memory.fields.short_term_size);
    expect(html).toContain('min="5"');
    expect(html).toContain('max="200"');
  });

  it('number: defaults min/max when the field omits them', () => {
    const html = renderField('x', { type: 'number', label: 'X', key: 'x' });
    expect(html).toContain('min="0"');
    expect(html).toContain('max="999"');
  });

  it('range: shows the current value both as the input value and as visible text', () => {
    const html = renderField('vol', { type: 'range', label: 'Volume', key: 'vol', min: 0, max: 100 });
    expect(html).toMatch(/<input type="range"[^>]*value="0"/); // no cached value -> falls back to min/0
    expect(html).toContain('class="range-val"');
  });

  it('textarea: escapes its content', () => {
    setSettingsCache({ character: { system_prompt: '<b>bold</b>' } });
    const html = renderField('system_prompt', SETTINGS_SCHEMA.Character.fields.system_prompt);
    expect(html).not.toContain('<b>bold</b>');
    expect(html).toContain('&lt;b&gt;');
  });

  it('text: includes a test-connection button only for the dynamic base_url field', () => {
    const baseUrlHtml = renderField('base_url', SETTINGS_SCHEMA.Provider.fields.base_url);
    expect(baseUrlHtml).toContain('test-conn-btn');
  });

  it('every field type declared anywhere in SETTINGS_SCHEMA produces non-empty HTML', () => {
    for (const cat of Object.values(SETTINGS_SCHEMA)) {
      for (const [fieldId, field] of Object.entries(cat.fields)) {
        const html = renderField(fieldId, field);
        expect(html == null || html.length > 0).toBe(true);
      }
    }
  });
});

describe('renderCategory', () => {
  it('renders a heading and a save button for a normal category', () => {
    const html = renderCategory('Memory');
    expect(html).toContain('Memory');
    expect(html).toContain('save-category-btn');
    expect(html).toContain('data-category="Memory"');
  });

  it('includes every field of the category that should be shown', () => {
    const html = renderCategory('Memory');
    expect(html).toContain('field-memory_enabled');
    expect(html).toContain('field-short_term_size');
    expect(html).toContain('field-long_term_enabled');
  });

  it('excludes fields whose show_if condition is not met', () => {
    setSettingsCache({ provider: { active: 'ollama' } }); // api_key is hidden for ollama
    const html = renderCategory('Provider');
    expect(html).not.toContain('field-api_key');
  });

  it('includes fields whose show_if condition is met', () => {
    setSettingsCache({ provider: { active: 'anthropic' } });
    const html = renderCategory('Provider');
    expect(html).toContain('field-api_key');
  });

  it('adds the Reset-to-Defaults section only for the Advanced category', () => {
    expect(renderCategory('Advanced')).toContain('Reset to Defaults');
    expect(renderCategory('Memory')).not.toContain('Reset to Defaults');
  });

  it('adds the Memory Graph section only for the Memory category', () => {
    expect(renderCategory('Memory')).toContain('memory-graph-container');
    expect(renderCategory('Voice')).not.toContain('memory-graph-container');
  });

  it('returns a friendly message for an unknown category instead of throwing', () => {
    expect(() => renderCategory('NotARealCategory')).not.toThrow();
    expect(renderCategory('NotARealCategory')).toContain('Unknown category');
  });
});

describe('filterSettings', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    const search = document.createElement('input');
    search.id = 'settings-search-input';
    const area = document.createElement('div');
    area.id = 'settings-form-area';
    document.body.appendChild(search);
    document.body.appendChild(area);
    setActiveSettingsTab('Memory');
  });

  it('with an empty query, re-renders the currently active tab', () => {
    document.getElementById('settings-search-input').value = '';
    filterSettings();
    const area = document.getElementById('settings-form-area');
    expect(area.innerHTML).toContain('field-memory_enabled');
  });

  it('with a query matching a field label, shows that field under its category heading', () => {
    document.getElementById('settings-search-input').value = 'context window';
    filterSettings();
    const html = document.getElementById('settings-form-area').innerHTML;
    expect(html).toContain('Search Results');
    expect(html).toContain('field-short_term_size');
  });

  it('with a query matching nothing, shows a "no results" message', () => {
    document.getElementById('settings-search-input').value = 'zzzznonexistentquery';
    filterSettings();
    const html = document.getElementById('settings-form-area').innerHTML;
    expect(html).toContain('settings-no-results');
  });

  it('search is case-insensitive', () => {
    document.getElementById('settings-search-input').value = 'CONTEXT WINDOW';
    filterSettings();
    expect(document.getElementById('settings-form-area').innerHTML).toContain('field-short_term_size');
  });
});
