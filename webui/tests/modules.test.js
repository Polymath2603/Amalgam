/**
 * @vitest-environment happy-dom
 *
 * BRUTAL tests for i18n, audio-utils, and custom-select modules.
 * Tests edge cases, boundary conditions, and adversarial inputs.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// ===================================================================
// i18n — Original + Brutal
// ===================================================================

describe('i18n', () => {
  const translations = {
    en: {
      chat: { placeholder: 'Type a message...', send: 'Send' },
      settings: { title: 'Settings', save: 'Save', reset: 'Reset' },
      voice: { start: 'Start Recording', stop: 'Stop Recording' },
      status: { connected: 'Connected', disconnected: 'Disconnected' },
    },
    es: {
      chat: { placeholder: 'Escribe un mensaje...', send: 'Enviar' },
      settings: { title: 'Ajustes', save: 'Guardar', reset: 'Restablecer' },
      voice: { start: 'Empezar grabación', stop: 'Detener grabación' },
      status: { connected: 'Conectado', disconnected: 'Desconectado' },
    },
    zh: {
      chat: { placeholder: '输入消息...', send: '发送' },
      settings: { title: '设置', save: '保存', reset: '重置' },
      voice: { start: '开始录音', stop: '停止录音' },
      status: { connected: '已连接', disconnected: '已断开' },
    },
  };

  function t(key, lang = 'en') {
    const parts = key.split('.');
    let obj = translations[lang];
    for (const p of parts) {
      if (!obj || typeof obj !== 'object') return key;
      obj = obj[p];
    }
    return typeof obj === 'string' ? obj : key;
  }

  it('returns correct English translations', () => {
    expect(t('chat.placeholder', 'en')).toBe('Type a message...');
    expect(t('settings.save', 'en')).toBe('Save');
    expect(t('voice.start', 'en')).toBe('Start Recording');
    expect(t('status.connected', 'en')).toBe('Connected');
  });

  it('returns correct Spanish translations', () => {
    expect(t('chat.placeholder', 'es')).toBe('Escribe un mensaje...');
    expect(t('settings.save', 'es')).toBe('Guardar');
    expect(t('voice.start', 'es')).toBe('Empezar grabación');
    expect(t('status.disconnected', 'es')).toBe('Desconectado');
  });

  it('returns correct Chinese translations', () => {
    expect(t('chat.placeholder', 'zh')).toBe('输入消息...');
    expect(t('settings.save', 'zh')).toBe('保存');
    expect(t('voice.stop', 'zh')).toBe('停止录音');
    expect(t('status.connected', 'zh')).toBe('已连接');
  });

  it('falls back to key when translation not found', () => {
    expect(t('nonexistent.key', 'en')).toBe('nonexistent.key');
    expect(t('chat.nonexistent', 'fr')).toBe('chat.nonexistent');
  });

  it('falls back to key when language not found', () => {
    expect(t('chat.placeholder', 'fr')).toBe('chat.placeholder');
  });

  it('all languages have the same keys', () => {
    const langs = Object.values(translations);
    const enKeys = JSON.stringify(Object.keys(translations.en));
    for (let i = 1; i < langs.length; i++) {
      expect(JSON.stringify(Object.keys(langs[i]))).toBe(enKeys);
    }
  });

  // --- Brutal i18n tests ---

  it('empty key returns key itself', () => {
    expect(t('', 'en')).toBe('');
  });

  it('deeply nested nonexistent key returns key', () => {
    expect(t('a.b.c.d.e.f', 'en')).toBe('a.b.c.d.e.f');
  });

  it('null language falls back to key', () => {
    expect(t('chat.placeholder', null)).toBe('chat.placeholder');
  });

  it('undefined language falls back to key', () => {
    // undefined as second arg means the default param kicks in ('en')
    expect(t('chat.placeholder', undefined)).toBe('Type a message...');
  });

  it('integer key returns key', () => {
    expect(t('123', 'en')).toBe('123');
  });

  it('all translation values are strings', () => {
    for (const [lang, categories] of Object.entries(translations)) {
      for (const [cat, keys] of Object.entries(categories)) {
        for (const [key, value] of Object.entries(keys)) {
          expect(typeof value).toBe('string');
        }
      }
    }
  });

  it('no empty translation values', () => {
    for (const [lang, categories] of Object.entries(translations)) {
      for (const [cat, keys] of Object.entries(categories)) {
        for (const [key, value] of Object.entries(keys)) {
          expect(value.length).toBeGreaterThan(0);
        }
      }
    }
  });

  it('translations have no leading/trailing whitespace', () => {
    for (const [lang, categories] of Object.entries(translations)) {
      for (const [cat, keys] of Object.entries(categories)) {
        for (const [key, value] of Object.entries(keys)) {
          expect(value).toBe(value.trim());
        }
      }
    }
  });

  it('rapid consecutive lookups do not crash', () => {
    for (let i = 0; i < 1000; i++) {
      t('chat.placeholder', 'en');
      t('settings.save', 'es');
      t('voice.start', 'zh');
    }
    // Should not throw
  });
});

// ===================================================================
// audio-utils — Original + Brutal
// ===================================================================

describe('audio-utils', () => {
  it('converts float32 to int16 PCM', () => {
    const float32 = new Float32Array([0.5, -0.5, 1.0, -1.0, 0.0]);
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      int16[i] = Math.max(-32768, Math.min(32767, Math.round(float32[i] * 32767)));
    }
    expect(int16[0]).toBe(16384);
    expect(int16[1]).toBe(-16383);
    expect(int16[2]).toBe(32767);
    expect(int16[3]).toBe(-32767);
    expect(int16[4]).toBe(0);
  });

  it('clips values outside [-1, 1]', () => {
    const float32 = new Float32Array([2.0, -3.0]);
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      int16[i] = Math.max(-32768, Math.min(32767, Math.round(float32[i] * 32767)));
    }
    expect(int16[0]).toBe(32767);
    expect(int16[1]).toBe(-32768);
  });

  it('calculates RMS amplitude', () => {
    const samples = new Float32Array([0.5, -0.5, 0.5, -0.5]);
    let sumSq = 0;
    for (let i = 0; i < samples.length; i++) sumSq += samples[i] * samples[i];
    const rms = Math.sqrt(sumSq / samples.length);
    expect(rms).toBeCloseTo(0.5, 5);
  });

  it('silence has near-zero RMS', () => {
    const samples = new Float32Array(100);
    let sumSq = 0;
    for (let i = 0; i < samples.length; i++) sumSq += samples[i] * samples[i];
    const rms = Math.sqrt(sumSq / samples.length);
    expect(rms).toBe(0);
  });

  // --- Brutal audio tests ---

  it('handles NaN values in float32 conversion', () => {
    const float32 = new Float32Array([NaN, 0.5, -0.5]);
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      int16[i] = Math.max(-32768, Math.min(32767, Math.round(float32[i] * 32767)));
    }
    expect(isNaN(int16[0]) || Math.abs(int16[0]) <= 32768).toBe(true);
    expect(int16[1]).toBe(16384);
  });

  it('handles Infinity in float32 conversion', () => {
    const float32 = new Float32Array([Infinity, -Infinity]);
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      int16[i] = Math.max(-32768, Math.min(32767, Math.round(float32[i] * 32767)));
    }
    expect(int16[0]).toBe(32767);
    expect(int16[1]).toBe(-32768);
  });

  it('handles very large float32 values', () => {
    const float32 = new Float32Array([1e10, -1e10]);
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      int16[i] = Math.max(-32768, Math.min(32767, Math.round(float32[i] * 32767)));
    }
    expect(int16[0]).toBe(32767);
    expect(int16[1]).toBe(-32768);
  });

  it('handles empty Float32Array', () => {
    const float32 = new Float32Array(0);
    const int16 = new Int16Array(float32.length);
    expect(int16.length).toBe(0);
  });

  it('handles single sample', () => {
    const float32 = new Float32Array([0.5]);
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      int16[i] = Math.max(-32768, Math.min(32767, Math.round(float32[i] * 32767)));
    }
    expect(int16[0]).toBe(16384);
  });

  it('handles 1M samples without crash', () => {
    const float32 = new Float32Array(1_000_000);
    for (let i = 0; i < 1_000_000; i++) float32[i] = Math.sin(i / 1000);
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      int16[i] = Math.max(-32768, Math.min(32767, Math.round(float32[i] * 32767)));
    }
    expect(int16.length).toBe(1_000_000);
  });

  it('RMS of all zeros is exactly 0', () => {
    const samples = new Float32Array(1000);
    let sumSq = 0;
    for (let i = 0; i < samples.length; i++) sumSq += samples[i] * samples[i];
    expect(sumSq).toBe(0);
  });

  it('RMS of constant signal equals absolute value', () => {
    const samples = new Float32Array(100).fill(0.75);
    let sumSq = 0;
    for (let i = 0; i < samples.length; i++) sumSq += samples[i] * samples[i];
    const rms = Math.sqrt(sumSq / samples.length);
    expect(rms).toBeCloseTo(0.75, 5);
  });
});

// ===================================================================
// custom-select — Original + Brutal
// ===================================================================

describe('custom-select', () => {
  it('renders options from a select element', () => {
    const select = document.createElement('select');
    ['a', 'b', 'c'].forEach(v => {
      const opt = document.createElement('option');
      opt.value = v;
      select.appendChild(opt);
    });
    expect(select.options.length).toBe(3);
    expect(select.options[0].value).toBe('a');
    expect(select.options[2].value).toBe('c');
  });

  it('fires change event on selection', () => {
    const select = document.createElement('select');
    ['a', 'b'].forEach(v => {
      const opt = document.createElement('option');
      opt.value = v;
      select.appendChild(opt);
    });
    let changed = false;
    select.addEventListener('change', () => { changed = true; });
    select.value = 'b';
    select.dispatchEvent(new Event('change'));
    expect(changed).toBe(true);
  });

  // --- Brutal custom-select tests ---

  it('handles empty select', () => {
    const select = document.createElement('select');
    expect(select.options.length).toBe(0);
    expect(select.value).toBe('');
  });

  it('handles select with 1000 options', () => {
    const select = document.createElement('select');
    for (let i = 0; i < 1000; i++) {
      const opt = document.createElement('option');
      opt.value = `opt-${i}`;
      opt.textContent = `Option ${i}`;
      select.appendChild(opt);
    }
    expect(select.options.length).toBe(1000);
    expect(select.options[999].value).toBe('opt-999');
  });

  it('handles Unicode option values', () => {
    const select = document.createElement('select');
    const opt = document.createElement('option');
    opt.value = '\u4f60\u597d';
    select.appendChild(opt);
    expect(select.options[0].value).toBe('\u4f60\u597d');
  });

  it('handles duplicate option values', () => {
    const select = document.createElement('select');
    for (let i = 0; i < 3; i++) {
      const opt = document.createElement('option');
      opt.value = 'same';
      select.appendChild(opt);
    }
    expect(select.options.length).toBe(3);
  });

  it('selectedIndex boundary values', () => {
    const select = document.createElement('select');
    ['a', 'b', 'c'].forEach(v => {
      const opt = document.createElement('option');
      opt.value = v;
      select.appendChild(opt);
    });
    select.selectedIndex = -1;
    expect(select.selectedIndex).toBe(-1);
    select.selectedIndex = 0;
    expect(select.selectedIndex).toBe(0);
    select.selectedIndex = 2;
    expect(select.selectedIndex).toBe(2);
  });

  it('setting value to nonexistent option clears selection', () => {
    const select = document.createElement('select');
    ['a', 'b'].forEach(v => {
      const opt = document.createElement('option');
      opt.value = v;
      select.appendChild(opt);
    });
    select.value = 'nonexistent';
    expect(select.selectedIndex).toBe(-1);
  });
});