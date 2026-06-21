/**
 * mcp-command.js — Interactive /mcp panel for toggling MCP servers
 *
 * Opens a keyboard-navigable overlay above the chat input that lists
 * all MCP servers with connection status and toggle switches.
 * Arrow keys navigate, Space toggles, Escape cancels, Enter confirms.
 */
import { BASE_URL } from './config.js';
import { showToast, escapeHtml } from './utils.js';
import { api } from './api-client.js';
import { getMcpServersCache, setMcpServersCache, getChatInput, getWs } from './state.js';

// ─── Panel state ───
let _isOpen = false;
let _selectedIndex = 0;
let _servers = [];          // current snapshot with enabled states
let _container = null;      // the overlay DOM element
let _onConfirm = null;      // callback to send config to backend

/**
 * Initialise once during app boot.
 * @param {Object} opts
 * @param {Function} [opts.onConfirm] — called with the final servers array on Enter
 */
export function initMcpCommand({ onConfirm } = {}) {
    _onConfirm = onConfirm || _defaultConfirm;
    _container = document.getElementById('mcp-panel-container');
    if (!_container) {
        console.warn('mcp-command: #mcp-panel-container not found in DOM');
        return;
    }
    _injectStyles();
}

/** Is the panel currently visible? */
export function isMcpPanelOpen() {
    return _isOpen;
}

/**
 * Open the panel.  Fetches fresh MCP server data and renders the list.
 */
export async function openMcpPanel() {
    if (_isOpen) { closeMcpPanel(); return; }

    // Fetch latest servers (use cache as fallback)
    try {
        const resp = await api(BASE_URL + '/api/mcp/servers');
        _servers = (resp?.servers || getMcpServersCache() || []).map(s => ({
            ...s,
            enabled: s.enabled !== false,  // normalise: treat undefined as true
        }));
    } catch {
        _servers = (getMcpServersCache() || []).map(s => ({
            ...s,
            enabled: s.enabled !== false,
        }));
    }

    if (!_servers.length) {
        showToast('No MCP servers configured', 'warning');
        return;
    }

    _selectedIndex = 0;
    _isOpen = true;
    _render();

    // Clear the chat input so it doesn't conflict
    const chatInput = getChatInput();
    if (chatInput) chatInput.value = '';
}

/** Close and clean up the panel. */
export function closeMcpPanel() {
    if (!_isOpen) return;
    _isOpen = false;
    _selectedIndex = 0;
    // Remove backdrop click listener before clearing
    const backdrop = _container?.querySelector('.mcp-panel-backdrop');
    if (backdrop) backdrop.removeEventListener('click', closeMcpPanel);
    if (_container) _container.innerHTML = '';
    // Return focus to chat input
    const chatInput = getChatInput();
    if (chatInput) chatInput.focus();
}

/**
 * Handle keydown events while the panel is open.
 * Call this from the chat input keydown handler when isMcpPanelOpen() is true.
 * @returns {boolean} true if the event was consumed
 */
export function handleMcpKeydown(e) {
    if (!_isOpen) return false;

    const items = _container?.querySelectorAll('.mcp-panel-item');
    if (!items?.length) return false;

    switch (e.key) {
        case 'ArrowDown':
        case 'ArrowRight':
            e.preventDefault();
            _selectedIndex = (_selectedIndex + 1) % items.length;
            _updateHighlight(items);
            return true;

        case 'ArrowUp':
        case 'ArrowLeft':
            e.preventDefault();
            _selectedIndex = (_selectedIndex - 1 + items.length) % items.length;
            _updateHighlight(items);
            return true;

        case ' ':
            e.preventDefault();
            _toggleServer(_selectedIndex);
            _updateHighlight(items); // re-render highlight + toggle state
            return true;

        case 'Enter':
            e.preventDefault();
            _confirmSelections();
            return true;

        case 'Escape':
            e.preventDefault();
            closeMcpPanel();
            return true;

        default:
            return false;
    }
}

// ─── Internal helpers ───

function _updateHighlight(items) {
    items.forEach((el, i) => el.classList.toggle('mcp-panel-selected', i === _selectedIndex));
    // Scroll into view
    items[_selectedIndex]?.scrollIntoView({ block: 'nearest' });
}

function _toggleServer(index) {
    if (index < 0 || index >= _servers.length) return;
    _servers[index].enabled = !_servers[index].enabled;

    // Update the visual toggle in-place
    const item = _container?.querySelectorAll('.mcp-panel-item')?.[index];
    if (!item) return;

    const s = _servers[index];
    item.classList.toggle('mcp-panel-disabled', !s.enabled);

    // Update status icon
    const icon = item.querySelector('.mcp-panel-status-icon');
    if (icon) {
        icon.textContent = s.enabled ? 'check_circle' : 'cancel';
        icon.classList.toggle('mcp-panel-online', s.enabled);
        icon.classList.toggle('mcp-panel-offline', !s.enabled);
    }

    // Update toggle slider
    const toggle = item.querySelector('.mcp-panel-toggle input');
    if (toggle) toggle.checked = s.enabled;
}

async function _confirmSelections() {
    // Apply the toggles to the state cache
    setMcpServersCache(_servers);

    // Send the batch settings update
    try {
        await fetch(`${BASE_URL}/api/settings/batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ settings: { 'mcp.servers': _servers } }),
        });
    } catch (err) {
        console.error('mcp-command: failed to save settings', err);
    }

    // Inform the backend via callback
    if (typeof _onConfirm === 'function') {
        _onConfirm(_servers);
    }

    const enabledCount = _servers.filter(s => s.enabled).length;
    showToast(`MCP: ${enabledCount}/${_servers.length} servers enabled`, 'success');
    closeMcpPanel();
}

function _defaultConfirm(servers) {
    // Notify the backend about MCP changes via WebSocket if available
    try {
        const ws = getWs();
        if (ws?.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'command',
                command: 'mcp_config_update',
                args: JSON.stringify(servers.map(s => ({ name: s.name, enabled: s.enabled }))),
            }));
        }
    } catch {
        // Non-critical
    }
}

function _render() {
    if (!_container) return;

    _container.innerHTML = `
        <div class="mcp-panel-backdrop"></div>
        <div class="mcp-panel" role="dialog" aria-label="MCP Server Manager" aria-modal="false">
            <div class="mcp-panel-header">
                <span class="material-icons-round" aria-hidden="true">extension</span>
                <span>MCP Servers</span>
                <span class="mcp-panel-count">${_servers.filter(s => s.enabled).length} / ${_servers.length} active</span>
            </div>
            <div class="mcp-panel-list" role="listbox" aria-label="MCP server list">
                ${_servers.map((s, i) => {
                    const connClass = s.connected ? 'connected' : 'disconnected';
                    const statusLabel = s.connected ? 'Connected' : 'Disconnected';
                    const cmd = (s.command || '') + ' ' + (s.args || []).join(' ');
                    const cmdShort = cmd.length > 45 ? cmd.slice(0, 45) + '...' : cmd;
                    return `
                        <div class="mcp-panel-item${i === _selectedIndex ? ' mcp-panel-selected' : ''}${!s.enabled ? ' mcp-panel-disabled' : ''}"
                             role="option" aria-selected="${i === _selectedIndex}"
                             data-index="${i}">
                            <div class="mcp-panel-item-info">
                                <span class="material-icons-round mcp-panel-status-icon ${s.enabled ? 'mcp-panel-online' : 'mcp-panel-offline'}"
                                      aria-hidden="true">${s.enabled ? 'check_circle' : 'cancel'}</span>
                                <div class="mcp-panel-item-text">
                                    <div class="mcp-panel-item-name">
                                        <span class="mcp-panel-conn-dot ${connClass}" title="${statusLabel}"></span>
                                        ${escapeHtml(s.name)}
                                    </div>
                                    <div class="mcp-panel-item-cmd">${escapeHtml(cmdShort || 'No command')}</div>
                                </div>
                            </div>
                            <label class="toggle mcp-panel-toggle" aria-label="Toggle ${escapeHtml(s.name)}">
                                <input type="checkbox" ${s.enabled ? 'checked' : ''} tabindex="-1">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>
                    `;
                }).join('')}
            </div>
            <div class="mcp-panel-footer">
                <span class="mcp-panel-hint">
                    <kbd>\u2191\u2193</kbd> Navigate &nbsp;
                    <kbd>Space</kbd> Toggle &nbsp;
                    <kbd>Enter</kbd> Confirm &nbsp;
                    <kbd>Esc</kbd> Cancel
                </span>
            </div>
        </div>
    `;

    // Backdrop click closes
    _container.querySelector('.mcp-panel-backdrop')?.addEventListener('click', closeMcpPanel);
}

function _injectStyles() {
    if (document.getElementById('mcp-panel-styles')) return;
    const style = document.createElement('style');
    style.id = 'mcp-panel-styles';
    style.textContent = `
        /* ── MCP Panel overlay ── */
        #mcp-panel-container:empty { display: none; }
        #mcp-panel-container {
            position: absolute; bottom: 0; left: 0; right: 0;
            z-index: 200; display: flex; flex-direction: column;
            align-items: center; pointer-events: none;
        }
        .mcp-panel-backdrop {
            position: fixed; inset: 0; background: rgba(0,0,0,0.35);
            pointer-events: auto; z-index: 199;
        }
        .mcp-panel {
            position: relative; z-index: 201;
            width: 90%; max-width: 440px; max-height: 360px;
            background: var(--bg-card, #1a1b24);
            border: 1px solid var(--border, #2d2e3b);
            border-bottom: none;
            border-radius: var(--radius, 12px) var(--radius, 12px) 0 0;
            box-shadow: 0 -8px 32px rgba(0,0,0,0.35);
            display: flex; flex-direction: column;
            pointer-events: auto;
            animation: mcpPanelSlideUp 0.18s ease-out;
        }
        @keyframes mcpPanelSlideUp {
            from { opacity: 0; transform: translateY(12px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        .mcp-panel-header {
            display: flex; align-items: center; gap: 0.5rem;
            padding: 0.7rem 1rem; border-bottom: 1px solid var(--border, #2d2e3b);
            font-weight: 600; font-size: 0.9rem;
        }
        .mcp-panel-header .material-icons-round { font-size: 1.1rem; color: var(--accent, #7d6cf1); }
        .mcp-panel-count {
            margin-left: auto; font-size: 0.75rem; font-weight: 400;
            color: var(--text-muted, #8e919e);
        }
        .mcp-panel-list {
            flex: 1; overflow-y: auto; padding: 0.4rem;
        }
        .mcp-panel-item {
            display: flex; align-items: center; justify-content: space-between;
            padding: 0.6rem 0.75rem; border-radius: var(--radius-sm, 8px);
            cursor: pointer; transition: background 0.1s;
            gap: 0.75rem;
        }
        .mcp-panel-item:hover { background: var(--bg-hover, #2d2e3b); }
        .mcp-panel-item.mcp-panel-selected {
            background: var(--accent-dim, rgba(125,108,241,0.15));
            outline: 1px solid var(--accent, #7d6cf1);
        }
        .mcp-panel-item.mcp-panel-disabled { opacity: 0.55; }
        .mcp-panel-item-info {
            display: flex; align-items: center; gap: 0.6rem; flex: 1; min-width: 0;
        }
        .mcp-panel-status-icon { font-size: 1rem; flex-shrink: 0; }
        .mcp-panel-status-icon.mcp-panel-online { color: var(--success, #00e699); }
        .mcp-panel-status-icon.mcp-panel-offline { color: var(--text-muted, #8e919e); }
        .mcp-panel-item-text { min-width: 0; }
        .mcp-panel-item-name {
            font-size: 0.85rem; font-weight: 600; display: flex; align-items: center; gap: 0.35rem;
        }
        .mcp-panel-item-cmd {
            font-size: 0.75rem; color: var(--text-muted, #8e919e);
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            margin-top: 0.1rem;
        }
        .mcp-panel-conn-dot {
            display: inline-block; width: 7px; height: 7px; border-radius: 50%;
            flex-shrink: 0;
        }
        .mcp-panel-conn-dot.connected { background: var(--success, #00e699); }
        .mcp-panel-conn-dot.disconnected { background: var(--text-muted, #8e919e); }
        .mcp-panel-toggle { flex-shrink: 0; }
        .mcp-panel-footer {
            padding: 0.45rem 1rem; border-top: 1px solid var(--border, #2d2e3b);
            text-align: center;
        }
        .mcp-panel-hint {
            font-size: 0.7rem; color: var(--text-muted, #8e919e);
        }
        .mcp-panel-hint kbd {
            display: inline-block; padding: 0.05rem 0.3rem;
            background: var(--bg-input, #23242e); border: 1px solid var(--border, #2d2e3b);
            border-radius: 3px; font-family: var(--font, 'Inter', sans-serif);
            font-size: 0.65rem; line-height: 1.4;
        }
    `;
    document.head.appendChild(style);
}
