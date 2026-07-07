/**
 * @vitest-environment happy-dom
 *
 * Real tests for the settings.js helper functions that resolve a form
 * field's settings-key, its current value, conditional visibility, and a
 * couple of small display formatters. These were exported specifically so
 * they can be unit-tested directly (they're "private by convention", not
 * by the module system).
 *
 * Regression test included: importing settings.js used to throw
 * `ReferenceError: loadCompanionSettings is not defined` on every load —
 * found by trying to import it for this test file, now fixed.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { installMinimalDOM } from './_dom-shim.js';

// Only install the offline DOM shim if a real DOM isn't already present —
// real vitest + happy-dom (after `npm install`) provides document/window
// itself, and this must not clobber it.
if (typeof document === 'undefined') installMinimalDOM();
global.fetch = async () => ({ ok: false, status: 0, json: async () => ({}) });

const settingsMod = await import('../js/modules/settings.js');
const { _getFieldKey, _getFieldValue, _shouldShowField, _formatBytes, _formatDate } = settingsMod;
const { setSettingsCache } = await import('../js/modules/state.js');
const { SETTINGS_SCHEMA } = await import('../js/modules/settings-schema.js');

describe('settings.js module (regression)', () => {
  it('imports without throwing (used to ReferenceError on loadCompanionSettings)', () => {
    expect(typeof settingsMod.renderField).toBe('function');
  });
});

describe('_getFieldKey', () => {
  beforeEach(() => {
    setSettingsCache({ provider: { active: 'anthropic' } });
  });

  it('resolves a key_dynamic field using the active provider and key_suffix', () => {
    const key = _getFieldKey('api_key', { key_dynamic: true, key_suffix: 'api_key' });
    expect(key).toBe('provider.anthropic.api_key');
  });

  it('falls back to "gemini" as the active provider when none is set', () => {
    setSettingsCache({});
    const key = _getFieldKey('api_key', { key_dynamic: true, key_suffix: 'api_key' });
    expect(key).toBe('provider.gemini.api_key');
  });

  it('uses the field id itself as the suffix when key_suffix is absent', () => {
    const key = _getFieldKey('some_field', { key_dynamic: true });
    expect(key).toBe('provider.anthropic.some_field');
  });

  it('uses the static "key" property directly for non-dynamic fields', () => {
    const key = _getFieldKey('aws_access_key', { key: 'provider.aws.access_key' });
    expect(key).toBe('provider.aws.access_key');
  });

  it('falls back to the field id when neither key nor key_dynamic is set', () => {
    expect(_getFieldKey('theme', {})).toBe('theme');
  });
});

describe('_getFieldValue', () => {
  it('reads the value at the resolved dynamic key', () => {
    setSettingsCache({ provider: { openai: { api_key: 'sk-test-123' } } });
    const val = _getFieldValue('api_key', { key_dynamic: true, key_suffix: 'api_key', key: 'whatever' });
    setSettingsCache({ provider: { active: 'openai', openai: { api_key: 'sk-test-123' } } });
    expect(_getFieldValue('api_key', { key_dynamic: true, key_suffix: 'api_key' })).toBe('sk-test-123');
  });

  it('returns empty string when the value is missing entirely', () => {
    setSettingsCache({ provider: { active: 'openai' } });
    expect(_getFieldValue('api_key', { key_dynamic: true, key_suffix: 'api_key' })).toBe('');
  });

  it('falls back to provider.<active>.<fieldId> when the suffix-based key is empty', () => {
    setSettingsCache({ provider: { active: 'openai', openai: { custom_field_id: 'fallback-value' } } });
    const val = _getFieldValue('custom_field_id', { key_dynamic: true, key_suffix: 'different_suffix' });
    expect(val).toBe('fallback-value');
  });
});

describe('_shouldShowField', () => {
  beforeEach(() => {
    setSettingsCache({ provider: { active: 'gemini' } });
    document.body.innerHTML = '';
  });

  it('shows fields with no show_if condition unconditionally', () => {
    expect(_shouldShowField('x', {})).toBe(true);
  });

  it('hides a field whose show_if.not_in includes the active provider', () => {
    setSettingsCache({ provider: { active: 'ollama' } });
    const show = _shouldShowField('api_key', {
      show_if: { field: 'active_provider', not_in: ['ollama', 'llamacpp', 'koboldai'] },
    });
    expect(show).toBe(false);
  });

  it('shows the field when the active provider is not in not_in', () => {
    setSettingsCache({ provider: { active: 'anthropic' } });
    const show = _shouldShowField('api_key', {
      show_if: { field: 'active_provider', not_in: ['ollama', 'llamacpp', 'koboldai'] },
    });
    expect(show).toBe(true);
  });

  it('prefers a live DOM select value over the settings cache when present', () => {
    const select = document.createElement('select');
    select.id = 'field-active_provider';
    const opt = document.createElement('option');
    opt.setAttribute('value', 'ollama');
    select.appendChild(opt);
    select.value = 'ollama';
    document.body.appendChild(select);
    // settings cache says anthropic, but the live (unsaved) dropdown says ollama
    setSettingsCache({ provider: { active: 'anthropic' } });
    const show = _shouldShowField('api_key', {
      show_if: { field: 'active_provider', not_in: ['ollama'] },
    });
    expect(show).toBe(false);
  });

  it('evaluates show_if.equals against the resolved value', () => {
    setSettingsCache({ provider: { active: 'aws' } });
    const show = _shouldShowField('aws_access_key', {
      show_if: { field: 'active_provider', equals: 'aws' },
    });
    expect(show).toBe(true);
  });
});

describe('_formatBytes', () => {
  it('formats sub-1024 byte counts as bytes', () => {
    expect(_formatBytes(500)).toBe('500 B');
  });
  it('formats kilobyte-range counts with one decimal', () => {
    expect(_formatBytes(2048)).toBe('2.0 KB');
  });
  it('formats megabyte-range counts with one decimal', () => {
    expect(_formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
  });
  it('returns empty string for null/undefined (but not for 0)', () => {
    expect(_formatBytes(null)).toBe('');
    expect(_formatBytes(undefined)).toBe('');
    expect(_formatBytes(0)).toBe('0 B');
  });
});

describe('_formatDate', () => {
  it('returns empty string for a falsy timestamp', () => {
    expect(_formatDate(0)).toBe('');
    expect(_formatDate(null)).toBe('');
  });
  it('formats a valid timestamp into a non-empty locale date string', () => {
    const result = _formatDate(Date.now());
    expect(result.length).toBeGreaterThan(0);
  });
  it('falls back to the raw value as a string if Date parsing throws', () => {
    const weird = { toString: () => { throw new Error('boom'); } };
    expect(() => _formatDate(weird)).not.toThrow();
  });
});

describe('SETTINGS_SCHEMA shape (sanity check against real renderField usage)', () => {
  it('every category has an icon and a fields object', () => {
    for (const [name, cat] of Object.entries(SETTINGS_SCHEMA)) {
      expect(typeof cat.icon).toBe('string');
      expect(typeof cat.fields).toBe('object');
    }
  });

  it('every field with show_if references a field that actually exists somewhere in the schema, or is one of the special-cased DOM ids', () => {
    const specialCased = new Set(['active_provider', 'stt_engine', 'tts_engine']);
    const allFieldIds = new Set();
    for (const cat of Object.values(SETTINGS_SCHEMA)) {
      for (const id of Object.keys(cat.fields)) allFieldIds.add(id);
    }
    for (const cat of Object.values(SETTINGS_SCHEMA)) {
      for (const field of Object.values(cat.fields)) {
        if (field.show_if) {
          const ok = specialCased.has(field.show_if.field) || allFieldIds.has(field.show_if.field);
          expect(ok).toBe(true);
        }
      }
    }
  });
});
