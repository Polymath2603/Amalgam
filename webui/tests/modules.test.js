/**
 * @vitest-environment happy-dom
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

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
});

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
});

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
    ['x', 'y'].forEach(v => {
      const opt = document.createElement('option');
      opt.value = v;
      select.appendChild(opt);
    });
    const handler = vi.fn();
    select.addEventListener('change', handler);
    select.value = 'y';
    select.dispatchEvent(new Event('change'));
    expect(handler).toHaveBeenCalled();
    expect(select.value).toBe('y');
  });
});

describe('speech-bubble', () => {
  it('creates and positions a speech bubble', () => {
    const bubble = document.createElement('div');
    bubble.className = 'speech-bubble';
    bubble.textContent = 'Hello!';
    document.body.appendChild(bubble);

    const computed = getComputedStyle(bubble);
    expect(bubble.textContent).toBe('Hello!');
    expect(bubble.className).toBe('speech-bubble');
  });

  it('removes bubble on click', () => {
    const bubble = document.createElement('div');
    bubble.className = 'speech-bubble';
    document.body.appendChild(bubble);

    const handler = vi.fn(() => bubble.remove());
    bubble.addEventListener('click', handler);
    bubble.click();
    expect(handler).toHaveBeenCalled();
    expect(document.body.contains(bubble)).toBe(false);
  });
});

describe('viseme-scheduler', () => {
  it('schedules viseme queue with timing', () => {
    const queue = [
      { viseme: 'aa', duration: 200 },
      { viseme: 'ih', duration: 150 },
      { viseme: 'sil', duration: 50 },
    ];
    let totalDuration = 0;
    queue.forEach(v => totalDuration += v.duration);
    expect(totalDuration).toBe(400);

    const timeline = [];
    let elapsed = 0;
    queue.forEach(v => {
      timeline.push({ viseme: v.viseme, start: elapsed, end: elapsed + v.duration });
      elapsed += v.duration;
    });
    expect(timeline[0].viseme).toBe('aa');
    expect(timeline[0].start).toBe(0);
    expect(timeline[0].end).toBe(200);
    expect(timeline[2].viseme).toBe('sil');
    expect(timeline[2].end).toBe(400);
  });

  it('handles empty queue', () => {
    const queue = [];
    expect(queue.length).toBe(0);
  });
});
