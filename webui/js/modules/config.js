/**
 * config.js — Application constants and URL derivation
 * Zero dependencies.
 */
export const IS_TAURI = window.location.protocol === 'tauri:' || window.location.protocol === 'asset:';
export const BASE_URL = IS_TAURI ? 'http://localhost:8000' : '';

function _deriveWsUrl() {
    if (IS_TAURI) return 'ws://localhost:8000';
    const loc = window.location;
    const wsProto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    let wsPort = loc.port || (loc.protocol === 'https:' ? '443' : '80');
    const DEV_SERVER_PORTS = new Set(['5173', '3000', '5174', '5175', '4173']);
    if (DEV_SERVER_PORTS.has(wsPort)) {
        wsPort = '8000';
    }
    return `${wsProto}//${loc.hostname}:${wsPort}`;
}

export const WS_BASE = _deriveWsUrl();
