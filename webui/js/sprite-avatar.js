/**
 * SpriteAvatar — lightweight 2D fallback avatar for low-end GPUs.
 * Completely decoupled from Three.js and the full AvatarRenderer.
 */

export class SpriteAvatar {
    constructor(container) {
        this.container = container;
        this.canvas = document.createElement('canvas');
        this.canvas.width = 256;
        this.canvas.height = 256;
        this.canvas.style.cssText = 'width:100%;height:100%;object-fit:contain;display:block';
        this.ctx = this.canvas.getContext('2d');
        container.innerHTML = '';
        container.appendChild(this.canvas);
        this._emotion = 'neutral';
        this._mouthOpen = 0;
        this.ready = true;
        this._blinkState = 'open';
        this._blinkTimer = Math.random() * 4000;
        this._animId = null;
        this._draw();
        this._startLoop();
    }

    _startLoop() {
        const loop = () => {
            this._animId = requestAnimationFrame(loop);
            this._blinkTimer += 16;
            if (this._blinkTimer > 3000 + Math.random() * 3000) {
                this._blinkState = this._blinkState === 'open' ? 'closing' : 'open';
                this._blinkTimer = 0;
            }
            this._draw();
        };
        this._animId = requestAnimationFrame(loop);
    }

    _draw() {
        const ctx = this.ctx, w = 256, h = 256;
        ctx.clearRect(0, 0, w, h);
        // Background
        ctx.fillStyle = '#1a1a2e'; ctx.beginPath();
        ctx.arc(w/2, h/2, 110, 0, Math.PI*2); ctx.fill();
        // Face
        ctx.fillStyle = '#ffe0bd'; ctx.beginPath();
        ctx.arc(w/2, h/2, 100, 0, Math.PI*2); ctx.fill();
        // Eyes
        const eyeY = h/2 - 10, blink = this._blinkState === 'open' ? 8 : 2;
        ctx.fillStyle = '#fff';
        ctx.beginPath(); ctx.ellipse(w/2-30, eyeY, 18, 20, 0, 0, Math.PI*2); ctx.fill();
        ctx.beginPath(); ctx.ellipse(w/2+30, eyeY, 18, 20, 0, 0, Math.PI*2); ctx.fill();
        ctx.fillStyle = '#2c2c3e';
        ctx.beginPath(); ctx.arc(w/2-30, eyeY, blink, 0, Math.PI*2); ctx.fill();
        ctx.beginPath(); ctx.arc(w/2+30, eyeY, blink, 0, Math.PI*2); ctx.fill();
        // Mouth
        const mo = Math.min(this._mouthOpen, 1);
        ctx.strokeStyle = '#c06'; ctx.lineWidth = 3;
        if (mo > 0.1) {
            ctx.beginPath(); ctx.ellipse(w/2, h/2+40, 15, 5+mo*15, 0, 0, Math.PI*2);
            ctx.fillStyle = '#400'; ctx.fill();
        } else {
            ctx.beginPath(); ctx.arc(w/2, h/2+40, 15, 0.1, Math.PI-0.1); ctx.stroke();
        }
        // Brows
        ctx.strokeStyle = '#333'; ctx.lineWidth = 3;
        const e = this._emotion, by = eyeY - 28;
        if (/happy|surprised/i.test(e)) {
            ctx.beginPath(); ctx.arc(w/2-37, by-5, 12, -Math.PI, 0); ctx.stroke();
            ctx.beginPath(); ctx.arc(w/2+15, by-5, 12, -Math.PI, 0); ctx.stroke();
        } else if (/angry|confused/i.test(e)) {
            ctx.beginPath(); ctx.moveTo(w/2-45, by-2); ctx.lineTo(w/2-23, by+4); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(w/2+8, by-2); ctx.lineTo(w/2-14, by+4); ctx.stroke();
        } else {
            ctx.beginPath(); ctx.moveTo(w/2-45, by); ctx.lineTo(w/2-23, by); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(w/2+8, by); ctx.lineTo(w/2-14, by); ctx.stroke();
        }
    }

    setEmotion(em) { this._emotion = em; }
    setMouthOpen(v) { this._mouthOpen = v; }
    setExpression() {}
    applyPhoneme() {}
    setHalfBodyMode() {}
    interact() {}
    loadVRM() {}
    startLipSync() {}
    stopLipSync() {}
    initIdleManager() {}
    setEmotion() {}
    setExpression() {}
    destroy() {
        if (this._animId) cancelAnimationFrame(this._animId);
        this.container.innerHTML = '';
    }
}
