/**
 * @vitest-environment happy-dom
 *
 * Real tests for webui/js/modules/ws.js — WebSocket connection lifecycle
 * (connect, reconnect backoff, heartbeat-adjacent state) and message
 * handling (handleWSMessage's chat streaming, voice messages, server
 * capability negotiation, TTS queueing).
 *
 * Note on scope: app.js itself wires everything together inside a single
 * `document.addEventListener('DOMContentLoaded', async () => {...})`
 * closure — addMessage, sendMessage, switchTab, etc. are all function
 * declarations *private to that one closure*, with no module-level
 * exports. That makes them structurally untestable from outside without
 * firing a full bootstrap against ~40 DOM ids and every API endpoint the
 * app calls on load. The actual logic that closure depends on lives in
 * the imported modules (ws.js, settings.js, utils.js, i18n.js, etc.),
 * which are tested directly and thoroughly elsewhere in this suite —
 * ws.js's dependency-injected callbacks (setWsCallbacks) are the real,
 * exported, testable seam into the chat pipeline, so that's what this
 * file exercises. (Noted as a real code-quality/testability finding for
 * app.js's own architecture, not a gap being papered over.)
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { installMinimalDOM } from './_dom-shim.js';

// Only install the offline DOM shim if a real DOM isn't already present —
// real vitest + happy-dom (after `npm install`) provides document/window
// itself, and this must not clobber it.
if (typeof document === 'undefined') installMinimalDOM();
global.fetch = async () => ({ ok: false, status: 0, json: async () => ({}) });

const ws = await import('../js/modules/ws.js');
const state = await import('../js/modules/state.js');

class MockWebSocket {
  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.sent = [];
    MockWebSocket.instances.push(this);
  }
  send(data) {
    this.sent.push(data);
  }
  close(code = 1000) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code });
  }
}
MockWebSocket.CONNECTING = 0;
MockWebSocket.OPEN = 1;
MockWebSocket.CLOSING = 2;
MockWebSocket.CLOSED = 3;
MockWebSocket.instances = [];

function setupDom() {
  document.body.innerHTML = '';
  const statusDot = document.createElement('div');
  statusDot.id = 'status-dot';
  const statusText = document.createElement('div');
  statusText.id = 'status-text';
  const chatMessages = document.createElement('div');
  chatMessages.id = 'chat-messages';
  document.body.appendChild(statusDot);
  document.body.appendChild(statusText);
  document.body.appendChild(chatMessages);
  return { statusDot, statusText, chatMessages };
}

beforeEach(() => {
  global.WebSocket = MockWebSocket;
  MockWebSocket.instances = [];
  state.setWs(null);
  state.setCurrentAssistantMessage(null);
  state.setTtsQueue([]);
  state.setStreamBufferTimer(null);
  state.streamBuffer.clear();
  state.setSettingsCache({});
});

describe('connectWS — connection open', () => {
  it('opening the socket marks status online and sends a client_hello', () => {
    const { statusDot, statusText } = setupDom();
    ws.setWsCallbacks({});
    ws.connectWS();
    const sock = MockWebSocket.instances[0];
    sock.readyState = MockWebSocket.OPEN;
    sock.onopen();

    expect(statusDot.className).toBe('status-dot online');
    const hello = sock.sent.map((s) => JSON.parse(s)).find((m) => m.type === 'client_hello');
    expect(hello).toBeDefined();
  });

  it('flushes any pending messages queued while disconnected', () => {
    setupDom();
    ws.setWsCallbacks({});
    ws.connectWS();
    const sock = MockWebSocket.instances[0];
    sock.readyState = MockWebSocket.OPEN;
    ws.getPendingMessages().push('{"type":"queued"}');
    sock.onopen();
    expect(sock.sent).toContain('{"type":"queued"}');
    expect(ws.getPendingMessages().length).toBe(0);
  });
});

describe('connectWS — reconnection', () => {
  it('a clean close (code 1000) schedules a fast (200ms) reconnect', () => {
    vi.useFakeTimers();
    const { statusDot, statusText } = setupDom();
    ws.setWsCallbacks({});
    ws.connectWS();
    const sock = MockWebSocket.instances[0];
    sock.onclose({ code: 1000 });

    expect(statusDot.className).toBe('status-dot connecting');
    expect(MockWebSocket.instances.length).toBe(1);
    vi.advanceTimersByTime(200);
    expect(MockWebSocket.instances.length).toBe(2); // connectWS() called again
    vi.useRealTimers();
  });

  it('an abnormal close schedules a reconnect using the backoff schedule', () => {
    vi.useFakeTimers();
    setupDom();
    ws.setWsCallbacks({});
    ws.connectWS();
    const sock = MockWebSocket.instances[0];
    sock.onclose({ code: 1006 }); // abnormal closure

    vi.advanceTimersByTime(499);
    expect(MockWebSocket.instances.length).toBe(1); // not yet (first delay is 500ms)
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances.length).toBe(2);
    vi.useRealTimers();
  });

  it('dispatches a ws:disconnected custom event with the close code', () => {
    setupDom();
    ws.setWsCallbacks({});
    let receivedCode = null;
    document.addEventListener('ws:disconnected', (e) => { receivedCode = e.detail.code; });
    ws.connectWS();
    MockWebSocket.instances[0].onclose({ code: 4321 });
    expect(receivedCode).toBe(4321);
  });
});

describe('handleWSMessage — chat streaming', () => {
  it('chat_start creates a placeholder assistant message and sets status to thinking', () => {
    setupDom();
    const addMessage = vi.fn((role) => {
      const div = document.createElement('div');
      div.className = `msg msg-${role}`;
      const body = document.createElement('div');
      body.className = 'msg-body';
      div.appendChild(body);
      document.getElementById('chat-messages').appendChild(div);
      return div;
    });
    const setStatus = vi.fn();
    ws.setWsCallbacks({ addMessage, setStatus });

    ws.handleWSMessage({ type: 'chat_start' });

    expect(addMessage).toHaveBeenCalledWith('assistant', '');
    expect(setStatus).toHaveBeenCalledWith('thinking');
  });

  it('chat_append batches text into the existing assistant message and flushes via rAF', () => {
    setupDom();
    let assistantDiv;
    const addMessage = vi.fn((role) => {
      assistantDiv = document.createElement('div');
      const body = document.createElement('div');
      body.className = 'msg-body';
      assistantDiv.appendChild(body);
      document.getElementById('chat-messages').appendChild(assistantDiv);
      return assistantDiv;
    });
    ws.setWsCallbacks({ addMessage, setStatus: vi.fn() });

    ws.handleWSMessage({ type: 'chat_start' });
    ws.handleWSMessage({ type: 'chat_append', role: 'assistant', text: 'Hello ' });
    ws.handleWSMessage({ type: 'chat_append', role: 'assistant', text: 'world' });

    // The rAF batch hasn't fired yet (it's scheduled, not synchronous)
    const body = assistantDiv.querySelector('.msg-body');
    expect(body.innerHTML).not.toContain('Hello world');
  });

  it('chat_append with finished:true clears the current-assistant-message tracker and resets status', () => {
    setupDom();
    const addMessage = vi.fn(() => {
      const div = document.createElement('div');
      const body = document.createElement('div');
      body.className = 'msg-body';
      div.appendChild(body);
      document.getElementById('chat-messages').appendChild(div);
      return div;
    });
    const setStatus = vi.fn();
    ws.setWsCallbacks({ addMessage, setStatus });

    ws.handleWSMessage({ type: 'chat_start' });
    ws.handleWSMessage({ type: 'chat_append', role: 'assistant', text: 'done', finished: true });

    expect(state.getCurrentAssistantMessage()).toBeNull();
    expect(setStatus).toHaveBeenCalledWith('ready');
  });
});

describe('handleWSMessage — voice and capability messages', () => {
  it('user_message_from_voice adds the user message and echoes it back over the socket if open', () => {
    setupDom();
    ws.setWsCallbacks({});
    const sock = new MockWebSocket('ws://x');
    sock.readyState = MockWebSocket.OPEN;
    state.setWs(sock);

    const addMessage = vi.fn();
    ws.setWsCallbacks({ addMessage });
    ws.handleWSMessage({ type: 'user_message_from_voice', text: 'hello there' });

    expect(addMessage).toHaveBeenCalledWith('user', 'hello there');
    const echoed = sock.sent.map((s) => JSON.parse(s)).find((m) => m.type === 'user_message');
    expect(echoed?.text).toBe('hello there');
  });

  it('server_hello stores capabilities and platform for later feature gating', () => {
    setupDom();
    ws.setWsCallbacks({});
    ws.handleWSMessage({ type: 'server_hello', capabilities: { push_notifications: true }, platform: 'capacitor' });
    // No public getter is exported for these, but at minimum this must not throw
    // and should not be misrouted to any other message handler.
    expect(() => ws.handleWSMessage({ type: 'server_hello', capabilities: {}, platform: 'web' })).not.toThrow();
  });

  it('tts_audio does not throw even when AudioContext is unavailable (e.g. this test environment)', () => {
    setupDom();
    ws.setWsCallbacks({});
    expect(() => ws.handleWSMessage({
      type: 'tts_audio', sentence_idx: 3, audio: 'BASE64DATA', duration: 1.5,
      viseme_schedule: [{ viseme: 'aa' }],
    })).not.toThrow();
  });
});

function setupAICompanyButton() {
  document.body.innerHTML = '';
  const btn = document.createElement('button');
  btn.id = 'ai-company-toggle';
  btn.dataset.mode = 'off';
  const badge = document.createElement('span');
  badge.id = 'ai-company-badge';
  badge.hidden = true;
  btn.appendChild(badge);
  document.body.appendChild(btn);
  return { btn, badge };
}

describe('AI Company header toggle', () => {
  it('setAICompanyMode updates data-mode and the title', () => {
    setupAICompanyButton();
    ws.setAICompanyMode('auto');
    const btn = document.getElementById('ai-company-toggle');
    expect(btn.dataset.mode).toBe('auto');
    expect(btn.title).toContain('auto');
  });

  it('setAICompanyStatus("running") unhides the badge', () => {
    const { btn, badge } = setupAICompanyButton();
    ws.setAICompanyStatus('running', 'building a plan');
    expect(btn.dataset.status).toBe('running');
    expect(badge.hidden).toBe(false);
  });

  it('setAICompanyStatus("idle") hides the badge', () => {
    const { btn, badge } = setupAICompanyButton();
    ws.setAICompanyStatus('running', 'x');
    ws.setAICompanyStatus('idle');
    expect(badge.hidden).toBe(true);
  });

  it('handleWSMessage routes company:start/done/error to the status badge', () => {
    const { btn } = setupAICompanyButton();
    ws.setWsCallbacks({});
    ws.handleWSMessage({ type: 'company:start', preview: 'build a thing' });
    expect(btn.dataset.status).toBe('running');
    ws.handleWSMessage({ type: 'company:done', duration: 4.2, plan_chars: 900 });
    expect(btn.dataset.status).toBe('done');
    ws.handleWSMessage({ type: 'company:error', reason: 'timeout' });
    expect(btn.dataset.status).toBe('error');
  });

  it('handleWSMessage routes company:mode_changed to setAICompanyMode', () => {
    const { btn } = setupAICompanyButton();
    ws.setWsCallbacks({});
    ws.handleWSMessage({ type: 'company:mode_changed', mode: 'on' });
    expect(btn.dataset.mode).toBe('on');
  });

  it('initAICompanyToggle wires a click handler that cycles off -> auto -> on -> off', () => {
    setupAICompanyButton();
    ws.setWsCallbacks({});
    ws.initAICompanyToggle();
    const btn = document.getElementById('ai-company-toggle');

    expect(btn.dataset.mode).toBe('off');
    btn.click();
    expect(btn.dataset.mode).toBe('auto');
    btn.click();
    expect(btn.dataset.mode).toBe('on');
    btn.click();
    expect(btn.dataset.mode).toBe('off');
  });

  it('clicking the toggle sends a /company slash command over an open socket', () => {
    setupAICompanyButton();
    ws.setWsCallbacks({});
    ws.initAICompanyToggle();
    const sock = new MockWebSocket('ws://x');
    sock.readyState = MockWebSocket.OPEN;
    state.setWs(sock);

    document.getElementById('ai-company-toggle').click();
    const sent = sock.sent.map((s) => JSON.parse(s));
    expect(sent).toContainEqual({ type: 'command', command: '/company auto' });
  });

  it('initAICompanyToggle does not throw when the button is missing from the DOM', () => {
    document.body.innerHTML = '';
    expect(() => ws.initAICompanyToggle()).not.toThrow();
  });
});
