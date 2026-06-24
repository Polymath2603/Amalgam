/**
 * health.js — Health bar management
 *
 * Health dots are created dynamically from /api/health responses.
 * The health-bar container starts empty and is populated on first refresh.
 */
import { BASE_URL } from './config.js';

let _healthInitialized = false;

function _ensureHealthBar() {
    const bar = document.getElementById('health-bar');
    if (!bar) return null;
    // Only clear on first init
    if (!_healthInitialized) {
        bar.innerHTML = '';
        _healthInitialized = true;
    }
    return bar;
}

function _ensureDot(name) {
    const bar = document.getElementById('health-bar');
    if (!bar) return null;
    let dot = bar.querySelector(`.health-dot[data-service="${name}"]`);
    if (!dot) {
        dot = document.createElement('span');
        dot.className = 'health-dot';
        dot.dataset.service = name;
        dot.textContent = '●';
        dot.dataset.status = 'unknown';
        bar.appendChild(dot);
    }
    return dot;
}

export function updateHealthBar(services) {
    if (!services) return;
    _ensureHealthBar();
    try {
        for (const [name, state] of Object.entries(services)) {
            const dot = _ensureDot(name);
            if (dot) {
                dot.dataset.status = state.status || 'unknown';
                dot.title = `${name.toUpperCase()}: ${state.status}${state.detail ? ' — ' + state.detail : ''}`;
            }
        }
    } catch (e) {
        console.warn('Failed to update health bar:', e);
    }
}

export async function refreshHealth() {
    try {
        const resp = await fetch(`${BASE_URL}/api/health`);
        if (resp.ok) {
            const data = await resp.json();
            if (data.services) {
                updateHealthBar(data.services);
            }
        }
    } catch (e) {
        console.warn('Health refresh failed (first failure logged):', e?.message || e);
    }
}
