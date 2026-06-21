/**
 * history.js — History panel UI + search
 */
import { BASE_URL } from './config.js';
import { escHtml } from './utils.js';
import { api } from './api-client.js';

let _historyLoadInProgress = false;
let _historySearchTimer = null;
let _historySearchAbort = null;
let _loadSessionFn = null;
let _showToastFn = null;
let _historyPanel = null;
let _historyList = null;

export function setHistoryDeps({ loadSession, showToast }) {
    _loadSessionFn = loadSession;
    _showToastFn = showToast;
    _historyPanel = document.getElementById('history-panel');
    _historyList = document.getElementById('history-list');
}

export function updateHistoryToggle() {
    if (!_historyList) _historyList = document.getElementById('history-list');
    const hasSessions = !!_historyList?.querySelector('[data-session-id]');
    const toggle = document.getElementById('history-toggle');
    if (toggle) toggle.style.display = hasSessions ? '' : 'none';
}

export async function loadHistory() {
    if (_historyLoadInProgress) return;
    _historyLoadInProgress = true;
    if (!_historyList) _historyList = document.getElementById('history-list');
    if (!_historyList) { _historyLoadInProgress = false; return; }
    try {
        const data = await api(BASE_URL + '/api/memory/sessions');
        _historyList.innerHTML = '';
        if (!data || !data.sessions || data.sessions.length === 0) {
            _historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);text-align:center">No conversations yet</div>';
            updateHistoryToggle();
            return;
        }
        data.sessions.forEach(session => {
            const item = document.createElement('div');
            item.className = 'history-item';
            item.dataset.sessionId = session.id;
            const time = session.last_active ? new Date(session.last_active).toLocaleString([], { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' }) : '';
            item.innerHTML = `
                <div class="history-content">
                    <div class="history-preview">${escHtml(session.preview)}</div>
                    <div class="history-time">${time} · ${session.message_count} messages</div>
                </div>
                <button class="history-delete" title="Delete conversation" aria-label="Delete conversation"><span class="material-icons-round" style="font-size:1rem">close</span></button>
            `;
            item.querySelector('.history-content').addEventListener('click', () => {
                location.hash = 'chat/' + session.id;
                _historyPanel?.classList.remove('open');
            });
            item.querySelector('.history-delete').addEventListener('click', async (e) => {
                e.stopPropagation();
                if (!confirm('Delete this conversation?')) return;
                try {
                    await api(BASE_URL + `/api/memory/session/${session.id}`, { method: 'DELETE' });
                    item.remove();
                    if (location.hash.replace('#', '').split('/')[1] === session.id) {
                        const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
                        if (res?.session_id) location.hash = 'chat/' + res.session_id;
                    }
                    updateHistoryToggle();
                } catch (err) {
                    console.warn('Failed to delete session:', err);
                    _showToastFn?.('Failed to delete session', 'danger');
                }
            });
            _historyList.appendChild(item);
        });
        updateHistoryToggle();
    } catch (e) {
        _historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted)">Failed to load history</div>';
        updateHistoryToggle();
    } finally {
        _historyLoadInProgress = false;
    }
}

export function initHistoryEvents() {
    _historyPanel = document.getElementById('history-panel');
    _historyList = document.getElementById('history-list');

    document.getElementById('new-chat-btn')?.addEventListener('click', async () => {
        const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
        if (res?.session_id) location.hash = 'chat/' + res.session_id;
        _showToastFn?.('New conversation started');
    });

    document.getElementById('history-toggle')?.addEventListener('click', async () => {
        _historyPanel?.classList.toggle('open');
        const isVisible = _historyPanel?.classList.contains('open');
        document.getElementById('history-toggle')?.setAttribute('aria-expanded', isVisible);
        if (isVisible) await loadHistory();
    });
    document.getElementById('close-history')?.addEventListener('click', () => {
        _historyPanel?.classList.remove('open');
    });

    document.getElementById('new-session-btn')?.addEventListener('click', async () => {
        const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
        if (res?.session_id) location.hash = 'chat/' + res.session_id;
        _historyPanel?.classList.remove('open');
        _showToastFn?.('New conversation started');
    });

    document.getElementById('clear-all-history')?.addEventListener('click', async () => {
        if (!confirm('Clear all conversation history?')) return;
        await api(BASE_URL + '/api/memory/clear', { method: 'POST' });
        const res = await api(BASE_URL + '/api/memory/session/current');
        if (res?.session_id) location.hash = 'chat/' + res.session_id;
        if (_historyList) _historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);text-align:center">No conversations yet</div>';
        updateHistoryToggle();
        _showToastFn?.('History cleared');
    });

    const historySearchInput = document.getElementById('history-search-input');
    if (historySearchInput) {
        historySearchInput.addEventListener('input', () => {
            clearTimeout(_historySearchTimer);
            const q = historySearchInput.value.trim();
            if (!q) {
                loadHistory();
                return;
            }
            _historySearchTimer = setTimeout(() => performHistorySearch(q), 300);
        });
    }

    window.addEventListener('hashchange', () => {
        const parts = location.hash.replace('#', '').split('/');
        if (parts[0] === 'chat' && parts[1] && _loadSessionFn) {
            _loadSessionFn(parts[1]);
        }
    });
}

async function performHistorySearch(query) {
    if (_historySearchAbort) _historySearchAbort.abort();
    _historySearchAbort = new AbortController();
    try {
        const res = await fetch(
            `${BASE_URL}/api/memory/search?q=${encodeURIComponent(query)}&scope=all`,
            { signal: _historySearchAbort.signal }
        );
        const data = await res.json();
        renderHistorySearchResults(data.results || []);
    } catch (e) {
        if (e.name !== 'AbortError') console.warn('History search failed:', e);
    }
}

function renderHistorySearchResults(results) {
    if (!_historyList) return;
    _historyList.innerHTML = '';
    if (results.length === 0) {
        _historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);text-align:center">No results found</div>';
        return;
    }
    results.forEach(r => {
        const item = document.createElement('div');
        item.className = 'history-search-result';
        const snippet = r.content ? r.content.substring(0, 120) : '';
        item.innerHTML = `
            <div class="result-session">${escHtml(r.session_id || 'unknown')}</div>
            <div class="result-snippet">${escHtml(snippet)}</div>
        `;
        item.addEventListener('click', () => {
            location.hash = 'chat/' + r.session_id;
            _historyPanel?.classList.remove('open');
        });
        _historyList.appendChild(item);
    });
}
