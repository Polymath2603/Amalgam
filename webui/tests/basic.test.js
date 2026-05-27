import { describe, it, expect } from 'vitest';

describe('Basic sanity', () => {
  it('math works', () => {
    expect(1 + 1).toBe(2);
  });

  it('DOM available', () => {
    expect(typeof document).toBe('object');
    expect(typeof window).toBe('object');
  });

  it('can create elements', () => {
    const div = document.createElement('div');
    div.className = 'test';
    div.textContent = 'hello';
    expect(div.outerHTML).toBe('<div class="test">hello</div>');
  });
});

describe('Settings field patterns', () => {
  const SETTINGS_FIELDS = {
    'gemini-api-key': 'provider.gemini.api_key',
    'deepseek-api-key': 'provider.deepseek.api_key',
    'azure-openai-api-key': 'provider.azure-openai.api_key',
  };

  it('settings fields map correctly', () => {
    expect(SETTINGS_FIELDS['gemini-api-key']).toBe('provider.gemini.api_key');
    expect(SETTINGS_FIELDS['deepseek-api-key']).toBe('provider.deepseek.api_key');
    expect(SETTINGS_FIELDS['azure-openai-api-key']).toBe('provider.azure-openai.api_key');
  });

  it('all field IDs use valid characters', () => {
    Object.keys(SETTINGS_FIELDS).forEach(id => {
      expect(id).toMatch(/^[a-z0-9-]+$/);
    });
  });
});
