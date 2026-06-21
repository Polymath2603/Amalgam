/**
 * health.js — Health bar management
 */
import { BASE_URL } from './config.js';

export function updateHealthBar(services) {
    if (!services) return;
    try {
        for (const [name, state] of Object.entries(services)) {
            const dot = document.querySelector(`.health-dot[data-service="${name}"]`);
            if (dot) {
                dot.dataset.status = state.status;
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
        // Silently fail — health bar just stays unknown
    }
}
