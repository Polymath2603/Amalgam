/**
 * utils.js — Shared utility functions
 * Zero dependencies.
 */

/**
 * Escape HTML special characters to prevent XSS.
 * This is the single canonical escaper for the entire codebase.
 */
export function escHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

export function _getNestedValue(obj, path) {
    if (!obj || !path) return undefined;
    if (obj[path] !== undefined) return obj[path];
    const parts = path.split('.');
    let cur = obj;
    for (const p of parts) {
        if (cur === null || cur === undefined) return undefined;
        cur = cur[p];
    }
    return cur;
}

export function showToast(message, type = 'system', options = {}) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const icons = {
        'success': 'check_circle',
        'danger': 'error',
        'critical': 'error',
        'warning': 'warning',
        'recoverable': 'warning',
        'system': 'info',
        'info': 'info',
    };
    const icon = icons[type] || 'info';

    const service = options.service ? `<span class="toast-service">${escHtml(options.service)}</span>` : '';
    const suggestion = options.suggestion ? `<span class="toast-suggestion">${escHtml(options.suggestion)}</span>` : '';
    const dismissBtn = type === 'critical' || type === 'danger'
        ? '<button class="toast-dismiss" onclick="this.parentElement.remove()"><span class="material-icons-round">close</span></button>'
        : '';

    toast.innerHTML = `
        <span class="material-icons-round toast-icon">${icon}</span>
        <div class="toast-content">
            ${service}
            <span class="toast-message">${escHtml(message)}</span>
            ${suggestion}
        </div>
        ${dismissBtn}
    `;

    container.appendChild(toast);

    const autoDismiss = {
        'success': 3000,
        'system': 3000,
        'info': 3000,
        'warning': 5000,
        'recoverable': 8000,
    };

    const duration = autoDismiss[type];
    if (duration) {
        let _dismissed = false;
        toast.addEventListener('click', () => { _dismissed = true; });
        setTimeout(() => {
            if (_dismissed) return;
            toast.style.animation = 'toast-out 0.3s ease forwards';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }
}

export function applyTheme(theme) {
    if (theme === 'dark') {
        document.documentElement.removeAttribute('data-theme');
    } else {
        document.documentElement.setAttribute('data-theme', theme);
    }
}

export function applyAccentColor(hex) {
    document.documentElement.style.setProperty('--accent', hex);
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    document.documentElement.style.setProperty('--accent-dim', `rgba(${r}, ${g}, ${b}, 0.15)`);
    document.querySelectorAll('#color-swatches .swatch').forEach(s => {
        s.classList.toggle('active', s.dataset.color === hex);
    });
    const picker = document.getElementById('accent-color-picker');
    if (picker) picker.value = hex;
}

export function detectGPUCapability() {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!gl) return { tier: 'software', reason: 'no-webgl' };

    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
    const renderer = debugInfo ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) : '';
    const vendor = debugInfo ? gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL) : '';
    const maxTexSize = gl.getParameter(gl.MAX_TEXTURE_SIZE);

    const isLowEnd = /(adreno 5|adreno 4|mali-?4|mali-?3|powervr|intel hd graphics|swiftshader|llvmpipe)/i.test(renderer);
    const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry/i.test(navigator.userAgent);
    const isVeryLowTex = maxTexSize < 4096;

    if (isLowEnd || isVeryLowTex) {
        return { tier: 'low', reason: renderer, renderer, vendor };
    }
    if (isMobile) {
        return { tier: 'medium', reason: renderer, renderer, vendor };
    }
    return { tier: 'high', reason: renderer, renderer, vendor };
}

export function trapFocus(modalElement) {
    if (!modalElement) return;
    const focusable = modalElement.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    const handler = (e) => {
        if (e.key !== 'Tab') return;
        if (e.shiftKey) {
            if (document.activeElement === first) {
                e.preventDefault();
                last?.focus();
            }
        } else {
            if (document.activeElement === last) {
                e.preventDefault();
                first?.focus();
            }
        }
    };

    modalElement.addEventListener('keydown', handler);
    modalElement._trapFocusHandler = handler;

    if (first) setTimeout(() => first.focus(), 50);
}
