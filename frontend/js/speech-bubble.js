export class SpeechBubble {
    constructor(avatarContainer, avatarRenderer) {
        this._renderer = avatarRenderer;
        this._visible = false;
        this._text = '';
        this._hideTimer = null;
        this._rafId = null;

        this._el = document.createElement('div');
        this._el.className = 'speech-bubble';
        this._el.innerHTML = '<div class="speech-bubble-text"></div><div class="speech-bubble-tail"></div>';
        this._el.style.cssText = `
            position: absolute;
            pointer-events: none;
            z-index: 100;
            opacity: 0;
            transition: opacity 0.25s ease;
            max-width: 280px;
        `;
        avatarContainer.style.position = 'relative';
        avatarContainer.appendChild(this._el);

        this._textEl = this._el.querySelector('.speech-bubble-text');
        const tail = this._el.querySelector('.speech-bubble-tail');
        tail.style.cssText = `
            width: 0; height: 0;
            border-left: 8px solid transparent;
            border-right: 8px solid transparent;
            border-top: 10px solid rgba(30, 30, 50, 0.9);
            margin: 0 auto;
        `;
        this._textEl.style.cssText = `
            background: rgba(30, 30, 50, 0.9);
            color: #e0e0f0;
            padding: 8px 14px;
            border-radius: 12px;
            font-size: 13px;
            line-height: 1.4;
            text-align: center;
            backdrop-filter: blur(4px);
            border: 1px solid rgba(255,255,255,0.1);
        `;
    }

    show(text, duration = 4000) {
        this._text = text;
        this._textEl.textContent = text;
        this._visible = true;
        this._el.style.opacity = '1';

        if (this._hideTimer) clearTimeout(this._hideTimer);
        if (duration > 0) {
            this._hideTimer = setTimeout(() => this.hide(), duration);
        }

        if (!this._rafId) this._track();
    }

    hide() {
        this._visible = false;
        this._el.style.opacity = '0';
        if (this._hideTimer) {
            clearTimeout(this._hideTimer);
            this._hideTimer = null;
        }
        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
            this._rafId = null;
        }
    }

    _track() {
        this._rafId = requestAnimationFrame(() => this._track());
        const pos = this._renderer._lastHeadScreenPos;
        if (pos && pos.visible) {
            this._el.style.display = 'block';
            this._el.style.left = (pos.x - this._el.offsetWidth / 2) + 'px';
            this._el.style.top = (pos.y - this._el.offsetHeight - 10) + 'px';
        } else {
            this._el.style.display = 'none';
        }
    }

    destroy() {
        this.hide();
        this._el.remove();
    }
}
