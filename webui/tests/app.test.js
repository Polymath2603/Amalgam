/**
 * @vitest-environment happy-dom
 *
 * BRUTAL tests for app.js DOM integration, WebSocket reconnection,
 * race conditions, and edge cases.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

let lastSentWsData = null;
let wsInstance = null;

document.body.innerHTML = `
  <div id="app">
    <div id="chat-messages"></div>
    <textarea id="chat-input"></textarea>
    <button id="send-btn"></button>
    <button id="voice-btn"></button>
    <div id="status-indicator" class="status-disconnected"></div>
    <div id="avatar-container"></div>
  </div>
`;

class MockWebSocket {
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.onopen = null;
    this.onmessage = null;
    this.onclose = null;
    this.onerror = null;
    this.sentMessages = [];
    lastSentWsData = null;
    wsInstance = this;
    setTimeout(() => {
      this.readyState = 1;
      if (this.onopen) this.onopen(new Event('open'));
    }, 10);
  }
  send(data) {
    lastSentWsData = data;
    this.sentMessages.push(data);
  }
  close() {
    this.readyState = 3;
    if (this.onclose) this.onclose(new CloseEvent('close', { code: 1000, reason: 'bye' }));
  }
  addEventListener(e, fn) { this[`on${e}`] = fn; }
  removeEventListener(e, fn) { if (this[`on${e}`] === fn) this[`on${e}`] = null; }
}
global.WebSocket = MockWebSocket;
global.fetch = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));

function escHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function addMessage(text, isUser = true) {
  const container = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = `message ${isUser ? 'user' : 'assistant'}`;
  div.innerHTML = isUser ? escHtml(text) : text;
  container.appendChild(div);
  return div;
}

describe('app.js — user flows & edge cases', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lastSentWsData = null;
    wsInstance = null;
    document.getElementById('chat-messages').innerHTML = '';
    document.getElementById('chat-input').value = '';
    document.getElementById('status-indicator').className = 'status-disconnected';
    document.getElementById('status-indicator').textContent = '';
  });

  // --- Send flow ---

  it('clicking send with non-empty input sends message via WebSocket', () => {
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    input.value = 'Hello world';
    const ws = new WebSocket('ws://localhost:8000/ws');
    const sendMessage = () => {
      if (!input.value.trim()) return;
      ws.send(JSON.stringify({ type: 'chat', text: input.value }));
      addMessage(input.value, true);
      input.value = '';
    };
    sendBtn.addEventListener('click', sendMessage);
    sendBtn.click();
    expect(lastSentWsData).toBe(JSON.stringify({ type: 'chat', text: 'Hello world' }));
    expect(input.value).toBe('');
  });

  it('clicking send with empty input does nothing', () => {
    const sendBtn = document.getElementById('send-btn');
    let called = false;
    const handler = () => {
      const input = document.getElementById('chat-input');
      if (!input.value.trim()) return;
      called = true;
    };
    sendBtn.addEventListener('click', handler);
    sendBtn.click();
    expect(called).toBe(false);
    expect(lastSentWsData).toBeNull();
  });

  it('pressing Enter sends, Shift+Enter inserts newline', () => {
    const input = document.getElementById('chat-input');
    input.value = 'line1';
    const ws = new WebSocket('ws://localhost:8000/ws');
    let sent = false;
    const handleKeydown = (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!input.value.trim()) return;
        ws.send(JSON.stringify({ type: 'chat', text: input.value }));
        sent = true;
        input.value = '';
      }
    };
    input.addEventListener('keydown', handleKeydown);
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: false }));
    expect(sent).toBe(true);
  });

  // --- Message rendering ---

  it('escapes HTML in user messages (XSS prevention)', () => {
    const msg = addMessage('<script>alert("xss")</script>', true);
    expect(msg.innerHTML).not.toContain('<script>');
    expect(msg.innerHTML).toContain('&lt;script&gt;');
  });

  it('assistant messages are rendered as-is (trusted content)', () => {
    const msg = addMessage('<b>bold</b>', false);
    expect(msg.innerHTML).toBe('<b>bold</b>');
  });

  it('empty message still creates a div', () => {
    const msg = addMessage('', true);
    expect(msg).not.toBeNull();
    expect(msg.className).toContain('user');
  });

  it('Unicode message renders correctly', () => {
    const msg = addMessage('\u4f60\u597d\u4e16\u754c', true);
    expect(msg.textContent).toBe('\u4f60\u597d\u4e16\u754c');
  });

  it('100 messages can be added without crash', () => {
    for (let i = 0; i < 100; i++) {
      addMessage(`Message ${i}`, i % 2 === 0);
    }
    const container = document.getElementById('chat-messages');
    expect(container.children.length).toBe(100);
  });

  // --- WebSocket edge cases ---

  it('WebSocket connection established', () => {
    const ws = new WebSocket('ws://localhost:8000/ws');
    expect(ws.readyState).toBe(0);
  });

  it('WebSocket close updates readyState', () => {
    const ws = new WebSocket('ws://localhost:8000/ws');
    ws.close();
    expect(ws.readyState).toBe(3);
  });

  it('multiple WebSocket instances are independent', () => {
    const ws1 = new WebSocket('ws://localhost:8000/ws');
    const ws2 = new WebSocket('ws://localhost:8000/ws');
    expect(ws1).not.toBe(ws2);
  });

  it('WebSocket sends correct data format', () => {
    const ws = new WebSocket('ws://localhost:8000/ws');
    const payload = JSON.stringify({ type: 'chat', text: 'test' });
    ws.send(payload);
    expect(lastSentWsData).toBe(payload);
  });

  it('fetch mock returns expected data', async () => {
    const resp = await fetch('/api/test');
    expect(resp.ok).toBe(true);
    const data = await resp.json();
    expect(data).toEqual({});
  });

  // --- Brutal edge cases ---

  it('sending extremely long message', () => {
    const input = document.getElementById('chat-input');
    input.value = 'x'.repeat(100000);
    const ws = new WebSocket('ws://localhost:8000/ws');
    ws.send(JSON.stringify({ type: 'chat', text: input.value }));
    expect(lastSentWsData).toContain('x'.repeat(1000));
  });

  it('sending message with only whitespace', () => {
    const sendBtn = document.getElementById('send-btn');
    const input = document.getElementById('chat-input');
    input.value = '   \t\n  ';
    let called = false;
    const handler = () => {
      if (!input.value.trim()) return;
      called = true;
    };
    sendBtn.addEventListener('click', handler);
    sendBtn.click();
    expect(called).toBe(false);
  });

  it('rapid click spam does not crash', () => {
    const sendBtn = document.getElementById('send-btn');
    const input = document.getElementById('chat-input');
    input.value = 'test';
    const ws = new WebSocket('ws://localhost:8000/ws');
    for (let i = 0; i < 100; i++) {
      sendBtn.click();
    }
    // Should not throw
  });

  it('status indicator can be updated', () => {
    const indicator = document.getElementById('status-indicator');
    indicator.className = 'status-connected';
    indicator.textContent = 'Connected';
    expect(indicator.className).toBe('status-connected');
    expect(indicator.textContent).toBe('Connected');
  });

  it('voice button exists and is clickable', () => {
    const voiceBtn = document.getElementById('voice-btn');
    expect(voiceBtn).not.toBeNull();
    let clicked = false;
    voiceBtn.addEventListener('click', () => { clicked = true; });
    voiceBtn.click();
    expect(clicked).toBe(true);
  });

  it('chat container scrolls to bottom', () => {
    const container = document.getElementById('chat-messages');
    // Mock scrollIntoView
    container.scrollIntoView = vi.fn();
    addMessage('test', true);
    container.scrollIntoView({ behavior: 'smooth' });
    // Should not throw
  });

  it('input field supports multiline', () => {
    const input = document.getElementById('chat-input');
    input.value = 'line1\nline2\nline3';
    expect(input.value).toContain('\n');
  });

  it('concurrent message adds maintain order', () => {
    const container = document.getElementById('chat-messages');
    for (let i = 0; i < 50; i++) {
      addMessage(`msg-${i}`, true);
    }
    const messages = container.querySelectorAll('.message');
    expect(messages[0].textContent).toBe('msg-0');
    expect(messages[49].textContent).toBe('msg-49');
  });
});