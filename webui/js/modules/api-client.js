/**
 * api-client.js — Generic fetch wrapper with timeout/abort
 * Zero dependencies.
 *
 * Options:
 *   - timeout:  ms before abort (default: DEFAULT_API_TIMEOUT_MS from config.js). Ignored when signal is provided.
 *   - signal:   external AbortSignal for caller-driven cancellation.
 *   - rawResponse: if true, return the Response object instead of parsing JSON.
 */
import { DEFAULT_API_TIMEOUT_MS } from './config.js';

export async function api(url, opts = {}) {
    // When the caller provides their own signal, skip the internal timeout
    // so their AbortController is the sole cancellation mechanism.
    const controller = opts.signal ? null : new AbortController();
    const timeout = controller ? setTimeout(() => controller.abort(), opts.timeout || DEFAULT_API_TIMEOUT_MS) : null;
    const signal = opts.signal || controller?.signal;

    try {
        const r = await fetch(url, { ...opts, signal });
        if (timeout) clearTimeout(timeout);
        if (!r.ok) {
            console.warn(`API ${r.status} (${url})`);
            return null;
        }
        if (opts.rawResponse) return r;
        try {
            return await r.json();
        } catch (jsonErr) {
            console.warn(`API non-JSON response (${url}):`, jsonErr);
            return null;
        }
    } catch (e) {
        if (timeout) clearTimeout(timeout);
        console.error(`API error (${url}):`, e);
        return null;
    }
}
