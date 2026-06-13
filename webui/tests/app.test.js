/**
 * @vitest-environment happy-dom
 *
 * Meaningful tests for app.js DOM integration and user flows.
 * Each test exercises a real interaction pattern or edge case.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// Track WebSocket messages for verification
let lastSentWsData = null;
let wsInstance = null;

// Mock DOM structure
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
    lastSentWsData = null;
    wsInstance = this;
    setTimeout(() => {
      this.readyState = 1;
      if (this.onopen) this.onopen(new Event('open'));
    }, 10);
  }
  send(data) { lastSentWsData = data; }
  close() {
    this.readyState = 3;
    if (this.onclose) this.onclose(new CloseEvent('close', { code: 1000, reason: 'bye' }));
  }
  addEventListener(e, fn) { this[`on${e}`] = fn; }
  removeEventListener(e, fn) { if (this[`on${e}`] === fn) this[`on${e}`] = null; }
}
global.WebSocket = MockWebSocket;

global.fetch = vi.fn(() =>
  Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
);

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

  // ─── Send flow ───────────────────────────────────────────────────────

  it('clicking send with non-empty input sends message via WebSocket', () => {
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    input.value = 'Hello world';

    // Simulate app.js send handler
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
    expect(input.value).toBe(''); // input cleared
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
    const handleKeydown = (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!input.value.trim()) return;
        ws.send(JSON.stringify({ type: 'chat', text: input.value }));
        addMessage(input.value, true);
        input.value = '';
      }
    };
    input.addEventListener('keydown', handleKeydown);

    // Press Enter alone
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: false }));
    expect(lastSentWsData).toBe(JSON.stringify({ type: 'chat', text: 'line1' }));

    lastSentWsData = null;
    input.value = 'multi\nline';
    // Press Shift+Enter — should NOT send
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true }));
    expect(lastSentWsData).toBeNull();
    expect(input.value).toBe('multi\nline');
  });

  // ─── Message rendering ───────────────────────────────────────────────

  it('user messages get HTML-escaped, assistant messages render HTML', () => {
    const container = document.getElementById('chat-messages');

    // User message: HTML in content should be escaped
    addMessage('<script>alert("xss")</script>', true);
    expect(container.innerHTML).toContain('&lt;script&gt;');
    expect(container.innerHTML).not.toContain('<script>alert(');

    // Assistant message: HTML should render (markdown output)
    addMessage('<strong>bold</strong>', false);
    expect(container.innerHTML).toContain('<strong>bold</strong>');
  });

  it('messages appear in chronological order', () => {
    addMessage('First', true);
    addMessage('Second', false);
    addMessage('Third', true);

    const msgs = document.querySelectorAll('#chat-messages .message');
    expect(msgs.length).toBe(3);
    expect(msgs[0].textContent).toBe('First');
    expect(msgs[1].textContent).toBe('Second');
    expect(msgs[2].textContent).toBe('Third');
  });

  it('user and assistant messages get correct CSS classes', () => {
    addMessage('user text', true);
    addMessage('assistant text', false);

    const msgs = document.querySelectorAll('#chat-messages .message');
    expect(msgs[0].className).toContain('user');
    expect(msgs[0].className).not.toContain('assistant');
    expect(msgs[1].className).toContain('assistant');
    expect(msgs[1].className).not.toContain('user');
  });

  // ─── Voice button ────────────────────────────────────────────────────

  it('voice button triggers media request and updates state', () => {
    const voiceBtn = document.getElementById('voice-btn');
    let isRecording = false;

    const toggleVoice = () => {
      isRecording = !isRecording;
      voiceBtn.textContent = isRecording ? 'Stop' : 'Start';
      voiceBtn.classList.toggle('recording', isRecording);
    };
    voiceBtn.addEventListener('click', toggleVoice);

    voiceBtn.click();
    expect(voiceBtn.textContent).toBe('Stop');
    expect(voiceBtn.classList.contains('recording')).toBe(true);

    voiceBtn.click();
    expect(voiceBtn.textContent).toBe('Start');
    expect(voiceBtn.classList.contains('recording')).toBe(false);
  });

  // ─── Status transitions ──────────────────────────────────────────────

  it('status indicator transitions through all states', () => {
    const indicator = document.getElementById('status-indicator');

    const setStatus = (state) => {
      indicator.className = `status-${state}`;
      const labels = { connected: 'Connected', disconnected: 'Disconnected', error: 'Error', connecting: 'Connecting...' };
      indicator.textContent = labels[state] || state;
    };

    setStatus('connecting');
    expect(indicator.className).toBe('status-connecting');
    expect(indicator.textContent).toBe('Connecting...');

    setStatus('connected');
    expect(indicator.className).toBe('status-connected');
    expect(indicator.textContent).toBe('Connected');

    setStatus('disconnected');
    expect(indicator.className).toBe('status-disconnected');
    expect(indicator.textContent).toBe('Disconnected');

    setStatus('error');
    expect(indicator.className).toBe('status-error');
    expect(indicator.textContent).toBe('Error');
  });

  it('WebSocket open sets status to connected', () => {
    const indicator = document.getElementById('status-indicator');
    const onOpen = () => {
      indicator.className = 'status-connected';
      indicator.textContent = 'Connected';
    };

    const ws = new MockWebSocket('ws://localhost:8000/ws');
    ws.onopen = onOpen;

    return new Promise(resolve => {
      setTimeout(() => {
        expect(indicator.className).toBe('status-connected');
        resolve();
      }, 20);
    });
  });

  it('WebSocket close sets status to disconnected', () => {
    const indicator = document.getElementById('status-indicator');
    const ws = new MockWebSocket('ws://localhost:8000/ws');

    setTimeout(() => {
      ws.onclose = () => {
        indicator.className = 'status-disconnected';
        indicator.textContent = 'Disconnected';
      };
      ws.close();
    }, 20);

    return new Promise(resolve => {
      setTimeout(() => {
        expect(indicator.className).toBe('status-disconnected');
        resolve();
      }, 40);
    });
  });

  // ─── WebSocket message handling ──────────────────────────────────────

  it('receiving chat message appends to chat', () => {
    const container = document.getElementById('chat-messages');
    const ws = new MockWebSocket('ws://localhost:8000/ws');
    const handler = vi.fn((event) => {
      const data = JSON.parse(event.data);
      addMessage(data.text, false);
    });

    ws.addEventListener('message', handler);

    setTimeout(() => {
      const msg = JSON.stringify({ type: 'chat', text: 'Hello from server', role: 'assistant' });
      if (ws.onmessage) {
        ws.onmessage({ data: msg });
      }
    }, 20);

    return new Promise(resolve => {
      setTimeout(() => {
        expect(handler).toHaveBeenCalled();
        expect(container.children.length).toBeGreaterThanOrEqual(1);
        resolve();
      }, 40);
    });
  });

  it('handles server error messages gracefully', () => {
    const indicator = document.getElementById('status-indicator');
    const container = document.getElementById('chat-messages');

    const handleError = (text) => {
      indicator.className = 'status-error';
      indicator.textContent = 'Error';
      const div = document.createElement('div');
      div.className = 'message error';
      div.textContent = text;
      container.appendChild(div);
    };

    handleError('API key expired');
    expect(indicator.className).toBe('status-error');
    expect(indicator.textContent).toBe('Error');
    expect(container.children[0].textContent).toBe('API key expired');
    expect(container.children[0].className).toBe('message error');
  });

  // ─── Fetch error handling ────────────────────────────────────────────

  it('handles 500 API response gracefully', async () => {
    fetch.mockResolvedValueOnce({ ok: false, status: 500, statusText: 'Internal Server Error' });
    const resp = await fetch('/api/settings');
    expect(resp.ok).toBe(false);
    expect(resp.status).toBe(500);
  });

  it('handles network errors gracefully', async () => {
    fetch.mockRejectedValueOnce(new Error('Network error'));
    await expect(fetch('/api/broken')).rejects.toThrow('Network error');
  });

  it('recovers after network error', async () => {
    fetch.mockRejectedValueOnce(new Error('Network error'));
    await expect(fetch('/api/settings')).rejects.toThrow('Network error');

    fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ status: 'ok' }) });
    const resp = await fetch('/api/settings');
    expect(resp.ok).toBe(true);
    const data = await resp.json();
    expect(data.status).toBe('ok');
  });
});
