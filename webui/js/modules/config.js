/**
 * config.js — Application constants and URL derivation
 * Zero dependencies.
 */

// ── Named constants for timeouts and polling intervals ─────────────
export const DEFAULT_API_TIMEOUT_MS = 30000;
export const WS_HEARTBEAT_INTERVAL_MS = 30000;
export const WS_PONG_TIMEOUT_MS = 10000;
export const WS_RECONNECT_DELAYS_MS = [500, 1000, 2000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000];
export const HEALTH_POLL_INTERVAL_MS = 30000;
export const METRICS_POLL_INTERVAL_MS = 10000;

export const IS_TAURI = window.location.protocol === 'tauri:' || window.location.protocol === 'asset:';

/**
 * Derive the base URL from (in order of precedence):
 *   1. window.__BACKEND_URL__  (runtime override, set by CI/build)
 *   2. <meta name="backend-url" content="...">  (deployment config)
 *   3. Tauri default: http://localhost:8000
 *   4. Web: empty string (same-origin relative URLs)
 */
function _deriveBaseUrl() {
    if (window.__BACKEND_URL__) return window.__BACKEND_URL__;
    const meta = document.querySelector('meta[name="backend-url"]');
    if (meta) return meta.getAttribute('content');
    if (IS_TAURI) return 'http://localhost:8000';
    return '';
}

export const BASE_URL = _deriveBaseUrl();

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
