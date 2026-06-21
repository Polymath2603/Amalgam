/**
 * mcp.js — MCP server/tool display
 */
import { BASE_URL } from './config.js';
import { escHtml } from './utils.js';
import { api } from './api-client.js';
import { getMcpServersCache, setMcpServersCache } from './state.js';

export async function loadMCP() {
    const servers = await api(BASE_URL + '/api/mcp/servers');
    const tools = await api(BASE_URL + '/api/mcp/tools');
    const list = document.getElementById('mcp-toggle-list');
    const grid = document.getElementById('tools-grid');
    if (servers?.servers && list) {
        setMcpServersCache(servers.servers);
        list.innerHTML = '';
        servers.servers.forEach(s => {
            const item = document.createElement('div');
            item.className = `mcp-item${s.enabled === false ? ' disabled' : ''}`;
            const icon = s.enabled !== false ? 'check_circle' : 'cancel';
            const iconClass = s.enabled !== false ? 'online' : 'offline';
            const connClass = s.connected ? 'connected' : 'disconnected';
            item.innerHTML = `
                <div class="mcp-item-info">
                    <span class="material-icons-round mcp-status-icon ${iconClass}">${icon}</span>
                    <div>
                        <strong><span class="conn-dot ${connClass}"></span> ${escHtml(s.name)}</strong>
                        <span class="muted">${escHtml((() => { const c = s.command + ' ' + (s.args || []).join(' '); return c.length > 40 ? c.slice(0, 40) + '...' : c; })())}</span>
                    </div>
                </div>
                <label class="toggle">
                    <input type="checkbox" class="mcp-enabled" data-name="${escHtml(s.name)}" ${s.enabled !== false ? 'checked' : ''}>
                    <span class="toggle-slider"></span>
                </label>
            `;
            const checkbox = item.querySelector('.mcp-enabled');
            checkbox.addEventListener('change', () => {
                const isEnabled = checkbox.checked;
                const statusIcon = item.querySelector('.mcp-status-icon');
                statusIcon.textContent = isEnabled ? 'check_circle' : 'cancel';
                statusIcon.className = `material-icons-round mcp-status-icon ${isEnabled ? 'online' : 'offline'}`;
                item.classList.toggle('disabled', !isEnabled);
                const mcpServers = getMcpServersCache();
                const server = mcpServers.find(srv => srv.name === s.name);
                if (server) server.enabled = isEnabled;
                const payload = { settings: { 'mcp.servers': mcpServers } };
                fetch(`${BASE_URL}/api/settings/batch`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                }).catch(() => {});
            });
            list.appendChild(item);
        });
    }

    if (tools?.tools && grid) {
        const enabledTools = tools.tools;

        grid.innerHTML = enabledTools.length === 0
            ? '<p class="muted">No tools connected</p>'
            : '';
        enabledTools.forEach(t => {
            const card = document.createElement('div');
            card.className = 'tool-card';
            const desc = (t.description || '').length > 40 ? (t.description || '').slice(0, 40) + '...' : (t.description || '');
            card.innerHTML = `<strong>${escHtml(t.name)}</strong><p>${escHtml(desc)}</p>`;
            grid.appendChild(card);
        });
    }
}
