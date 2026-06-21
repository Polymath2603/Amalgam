/**
 * api-client.js — Generic fetch wrapper with timeout/abort
 * Zero dependencies.
 */

export async function api(url, opts = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), opts.timeout || 30000);
    try {
        const r = await fetch(url, { ...opts, signal: controller.signal });
        clearTimeout(timeout);
        if (!r.ok) {
            console.warn(`API ${r.status} (${url})`);
            return null;
        }
        const text = await r.text();
        if (!text) return null;
        return JSON.parse(text);
    } catch (e) {
        clearTimeout(timeout);
        console.error(`API error (${url}):`, e);
        return null;
    }
}
