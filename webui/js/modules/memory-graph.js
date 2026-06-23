/**
 * memory-graph.js — Canvas-based force-directed graph visualization
 * for memory sessions. Shows sessions as nodes with chronological edges.
 */
import { BASE_URL } from './config.js';
import { api } from './api-client.js';
import { escHtml } from './utils.js';

// ── Force-directed simulation ──────────────────────────────────────────

class ForceGraph {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.nodes = [];
        this.edges = [];
        this.animId = null;
        this.paused = false;
        this.dragged = null;
        this.dragOffset = { x: 0, y: 0 };
        this.hovered = null;
        this.selected = null;
        this.onNodeClick = null;
        this.center = { x: canvas.width / 2, y: canvas.height / 2 };

        this.repulsion = 8000;
        this.attraction = 0.005;
        this.centerGravity = 0.01;
        this.damping = 0.85;
        this.minVelocity = 0.1;

        this._bindEvents();
    }

    resize() {
        const rect = this.canvas.parentElement.getBoundingClientRect();
        this.canvas.width = rect.width;
        this.canvas.height = rect.height;
        this.center = { x: this.canvas.width / 2, y: this.canvas.height / 2 };
    }

    setData(nodes, edges) {
        const angleStep = (2 * Math.PI) / Math.max(nodes.length, 1);
        nodes.forEach((n, i) => {
            if (!n.x) {
                const angle = i * angleStep + Math.random() * 0.5;
                const radius = 80 + Math.random() * 60;
                n.x = this.center.x + Math.cos(angle) * radius;
                n.y = this.center.y + Math.sin(angle) * radius;
            }
            n.vx = n.vx || 0;
            n.vy = n.vy || 0;
            n.radius = 20;
            n.pinned = n.pinned || false;
        });
        this.nodes = nodes;
        this.edges = edges;
    }

    start() {
        this.paused = false;
        this._tick();
    }

    stop() {
        this.paused = true;
        if (this.animId) {
            cancelAnimationFrame(this.animId);
            this.animId = null;
        }
    }

    _tick() {
        if (this.paused) return;
        this._simulate();
        this._draw();
        this.animId = requestAnimationFrame(() => this._tick());
    }

    _simulate() {
        const { nodes, edges } = this;
        const n = nodes.length;
        if (n === 0) return;

        // Coulomb repulsion
        for (let i = 0; i < n; i++) {
            for (let j = i + 1; j < n; j++) {
                const a = nodes[i], b = nodes[j];
                let dx = b.x - a.x, dy = b.y - a.y;
                let dist = Math.sqrt(dx * dx + dy * dy) || 1;
                const force = this.repulsion / (dist * dist);
                const fx = (dx / dist) * force, fy = (dy / dist) * force;
                if (!a.pinned) { a.vx -= fx; a.vy -= fy; }
                if (!b.pinned) { b.vx += fx; b.vy += fy; }
            }
        }

        // Hooke attraction along edges
        for (const edge of edges) {
            const a = nodes[edge.source], b = nodes[edge.target];
            if (!a || !b) continue;
            let dx = b.x - a.x, dy = b.y - a.y;
            let dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const force = this.attraction * (dist - (edge.restLength || 150));
            const fx = (dx / dist) * force, fy = (dy / dist) * force;
            if (!a.pinned) { a.vx += fx; a.vy += fy; }
            if (!b.pinned) { b.vx -= fx; b.vy -= fy; }
        }

        // Center gravity
        for (const node of nodes) {
            if (node.pinned) continue;
            node.vx += (this.center.x - node.x) * this.centerGravity;
            node.vy += (this.center.y - node.y) * this.centerGravity;
        }

        // Apply velocities with damping
        let totalSpeed = 0;
        for (const node of nodes) {
            if (node.pinned) continue;
            node.vx *= this.damping;
            node.vy *= this.damping;
            const speed = Math.sqrt(node.vx * node.vx + node.vy * node.vy);
            if (speed > this.minVelocity) {
                node.x += node.vx;
                node.y += node.vy;
                totalSpeed += speed;
            }
        }

        // Slow simulation as it settles
        if (totalSpeed < 1 && this.attraction > 0.001) {
            this.attraction *= 0.995;
            this.centerGravity *= 0.998;
        }
    }

    _draw() {
        const { ctx, nodes, edges, canvas } = this;
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Edges
        for (const edge of edges) {
            const a = nodes[edge.source], b = nodes[edge.target];
            if (!a || !b) continue;
            const hl = this.hovered !== null && (edge.source === this.hovered || edge.target === this.hovered);
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.strokeStyle = hl ? 'rgba(100, 180, 255, 0.6)' : 'rgba(150, 150, 150, 0.25)';
            ctx.lineWidth = hl ? 2 : 1;
            ctx.stroke();
        }

        // Nodes
        for (let i = 0; i < nodes.length; i++) {
            const n = nodes[i];
            const isHov = this.hovered === i;
            const isSel = this.selected === i;

            ctx.beginPath();
            ctx.arc(n.x, n.y, n.radius, 0, 2 * Math.PI);
            const grad = ctx.createRadialGradient(n.x - 4, n.y - 4, 2, n.x, n.y, n.radius);
            if (n.isCurrent) {
                grad.addColorStop(0, '#4fc3f7');
                grad.addColorStop(1, '#0288d1');
            } else {
                grad.addColorStop(0, '#81c784');
                grad.addColorStop(1, '#388e3c');
            }
            ctx.fillStyle = grad;
            ctx.fill();

            if (isHov || isSel) {
                ctx.strokeStyle = isSel ? '#ffd54f' : '#ffffff';
                ctx.lineWidth = isSel ? 3 : 2;
                ctx.stroke();
            }

            const label = n.label || ('Session ' + (i + 1));
            ctx.fillStyle = '#e0e0e0';
            ctx.font = '11px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(label.length > 15 ? label.slice(0, 14) + '\u2026' : label, n.x, n.y + n.radius + 14);
        }
    }

    _bindEvents() {
        const c = this.canvas;

        c.addEventListener('mousedown', (e) => {
            const idx = this._nodeAt(e);
            if (idx !== null) {
                this.dragged = idx;
                this.nodes[idx].pinned = true;
                const r = c.getBoundingClientRect();
                this.dragOffset.x = e.clientX - r.left - this.nodes[idx].x;
                this.dragOffset.y = e.clientY - r.top - this.nodes[idx].y;
            }
        });

        c.addEventListener('mousemove', (e) => {
            const r = c.getBoundingClientRect();
            const mx = e.clientX - r.left, my = e.clientY - r.top;
            if (this.dragged !== null) {
                this.nodes[this.dragged].x = mx - this.dragOffset.x;
                this.nodes[this.dragged].y = my - this.dragOffset.y;
                return;
            }
            const idx = this._hitTest(mx, my);
            if (idx !== this.hovered) {
                this.hovered = idx;
                c.style.cursor = idx !== null ? 'pointer' : 'default';
            }
        });

        c.addEventListener('mouseup', (e) => {
            if (this.dragged !== null) {
                const idx = this.dragged;
                this.dragged = null;
                const r = c.getBoundingClientRect();
                const mx = e.clientX - r.left - this.dragOffset.x;
                const my = e.clientY - r.top - this.dragOffset.y;
                const n = this.nodes[idx];
                if (Math.abs(mx - n.x) < 5 && Math.abs(my - n.y) < 5) {
                    this.selected = idx;
                    this.onNodeClick?.(n);
                }
            }
        });

        c.addEventListener('mouseleave', () => { this.dragged = null; this.hovered = null; });
        c.addEventListener('dblclick', (e) => {
            const idx = this._nodeAt(e);
            if (idx !== null) this.nodes[idx].pinned = false;
        });
        c.addEventListener('touchstart', (e) => {
            const t = e.touches[0];
            const idx = this._nodeAt({ clientX: t.clientX, clientY: t.clientY });
            if (idx !== null) { this.selected = idx; this.onNodeClick?.(this.nodes[idx]); }
        }, { passive: true });
    }

    _nodeAt(e) {
        const r = this.canvas.getBoundingClientRect();
        return this._hitTest(e.clientX - r.left, e.clientY - r.top);
    }

    _hitTest(mx, my) {
        for (let i = this.nodes.length - 1; i >= 0; i--) {
            const n = this.nodes[i];
            const dx = mx - n.x, dy = my - n.y;
            if (dx * dx + dy * dy <= (n.radius + 5) * (n.radius + 5)) return i;
        }
        return null;
    }
}

// ── Public API ─────────────────────────────────────────────────────────

// ── Internal helpers called by initMemoryGraph ────────────────────────

async function _loadGraphData(graph, container) {
    const loadingEl = document.getElementById('memory-graph-loading');
    if (loadingEl) loadingEl.style.display = 'block';
    try {
        const data = await api(BASE_URL + '/api/memory/sessions');
        if (!data || !data.sessions) {
            _showEmpty(graph, container, 'No sessions found. Start a conversation to see your memory graph.');
            return;
        }
        const nodes = [];
        const edges = [];
        data.sessions.forEach((sid, i) => {
            nodes.push({
                id: sid,
                label: sid.length > 20 ? sid.slice(0, 8) + '\u2026' : sid,
                isCurrent: sid === data.current,
                sessionId: sid,
                data: null,
            });
            if (i > 0) edges.push({ source: i - 1, target: i, restLength: 150 });
        });
        graph.setData(nodes, edges);
        graph.resize();
        graph.start();
    } catch (e) {
        console.error('Memory graph load failed:', e);
        _showEmpty(graph, container, 'Failed to load memory data.');
    } finally {
        if (loadingEl) loadingEl.style.display = 'none';
    }
}

async function _searchMemory(query, graph, container) {
    const infoEl = document.getElementById('memory-graph-info-content');
    const infoPanel = document.getElementById('memory-graph-info');
    if (!infoEl || !infoPanel) return;
    if (!query.trim()) { infoPanel.classList.add('hidden'); return; }

    const data = await api(BASE_URL + '/api/memory/search?q=' + encodeURIComponent(query) + '&scope=all');
    if (!data || !data.results || data.results.length === 0) {
        infoEl.innerHTML = '<p class="muted">No results found.</p>';
        infoPanel.classList.remove('hidden');
        return;
    }

    let html = '<h4 class="memory-info-title">Search results for "' + escHtml(query) + '"</h4><div class="memory-search-results">';
    for (const r of data.results) {
        const content = r.content || r.text || '\u2026';
        html += '<div class="memory-search-item"><div class="memory-search-snippet">' + escHtml(content.slice(0, 200)) +
            '</div>' + (r.session_id ? '<div class="memory-search-meta">' + escHtml(r.session_id.slice(0, 12)) + '\u2026</div>' : '') + '</div>';
    }
    html += '</div>';
    infoEl.innerHTML = html;
    infoPanel.classList.remove('hidden');

    graph.nodes.forEach(n => { n.radius = data.results.some(r => r.session_id === n.sessionId) ? 28 : 16; });
}

async function _showNodeInfo(node, graph) {
    const infoEl = document.getElementById('memory-graph-info-content');
    const infoPanel = document.getElementById('memory-graph-info');
    if (!infoEl || !infoPanel) return;

    const sessionId = node.sessionId || node.id;
    infoEl.innerHTML = '<div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text"></div>';
    infoPanel.classList.remove('hidden');

    const sessionData = await api(BASE_URL + '/api/memory/session/' + encodeURIComponent(sessionId));
    if (!sessionData) {
        infoEl.innerHTML = '<p class="muted">Failed to load session details.</p>';
        return;
    }

    const msgs = sessionData.messages || [];
    const firstMsg = msgs[0]?.content || msgs[0]?.text || '(empty)';
    infoEl.innerHTML =
        '<h4 class="memory-info-title">Session Details</h4>' +
        '<div class="memory-info-field"><span class="memory-info-label">ID</span><span class="memory-info-value">' + escHtml(sessionId.slice(0, 16)) + '\u2026</span></div>' +
        '<div class="memory-info-field"><span class="memory-info-label">Messages</span><span class="memory-info-value">' + msgs.length + '</span></div>' +
        '<div class="memory-info-field"><span class="memory-info-label">Preview</span><span class="memory-info-value">' + escHtml(firstMsg.slice(0, 150)) + (firstMsg.length > 150 ? '\u2026' : '') + '</span></div>' +
        '<h4 class="memory-info-title" style="margin-top:12px">Connected Sessions</h4><div class="memory-connected-list">' +
        graph.edges
            .filter(e => graph.nodes[e.source]?.sessionId === sessionId || graph.nodes[e.target]?.sessionId === sessionId)
            .map(e => {
                const ci = graph.nodes[e.source]?.sessionId === sessionId ? e.target : e.source;
                const cn = graph.nodes[ci];
                return cn ? '<button class="btn-ghost memory-connected-item" data-idx="' + ci + '"><span class="material-icons-round" style="font-size:16px">subdirectory_arrow_right</span>' + escHtml(cn.label) + '</button>' : '';
            }).join('') +
        '</div>';

    infoEl.querySelectorAll('.memory-connected-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const idx = parseInt(btn.dataset.idx);
            if (graph.nodes[idx]) { graph.selected = idx; _showNodeInfo(graph.nodes[idx], graph); }
        });
    });
}

function _showEmpty(graph, container, msg) {
    graph.setData([], []);
    graph.resize();
    graph._draw();
    const infoEl = document.getElementById('memory-graph-info-content');
    const infoPanel = document.getElementById('memory-graph-info');
    if (infoEl && infoPanel) { infoEl.innerHTML = '<p class="muted">' + escHtml(msg) + '</p>'; infoPanel.classList.remove('hidden'); }
}

// ── Module-level state ─────────────────────────────────────────────────

let _graphInstance = null;

export async function initMemoryGraph() {
    destroyMemoryGraph();

    const container = document.getElementById('memory-graph-container');
    if (!container) return;

    // Clear existing content (keep container, replace children)
    container.innerHTML = '';

    // Build our graph structure inside the existing container
    const wrap = document.createElement('div');
    wrap.className = 'memory-graph-canvas-wrap';
    wrap.style.cssText = 'width:100%;height:100%;position:relative;';
    container.appendChild(wrap);

    const header = document.createElement('div');
    header.className = 'memory-graph-header';
    header.style.cssText = 'position:absolute;top:8px;left:8px;right:8px;z-index:5;display:flex;gap:8px;';
    header.innerHTML =
        '<input type="text" id="memory-graph-search" class="field-input" style="flex:1;font-size:12px;padding:4px 8px;" placeholder="Search memory..." aria-label="Search memory">' +
        '<button id="memory-graph-refresh" class="btn-ghost" style="padding:4px 8px;" aria-label="Refresh graph"><span class="material-icons-round" style="font-size:1rem;">refresh</span></button>';
    wrap.appendChild(header);

    const canvas = document.createElement('canvas');
    canvas.id = 'memory-graph-canvas';
    canvas.style.cssText = 'width:100%;height:100%;display:block;';
    wrap.appendChild(canvas);

    const legend = document.createElement('div');
    legend.id = 'memory-graph-legend';
    legend.style.cssText = 'position:absolute;bottom:8px;left:8px;display:flex;gap:14px;font-size:11px;color:var(--text-muted);pointer-events:none;';
    legend.innerHTML =
        '<span><span class="legend-dot current"></span> Current session</span>' +
        '<span><span class="legend-dot past"></span> Past sessions</span>';
    wrap.appendChild(legend);

    const info = document.createElement('div');
    info.id = 'memory-graph-info';
    info.className = 'memory-graph-info hidden';
    info.innerHTML =
        '<button class="memory-graph-close" id="memory-graph-close" aria-label="Close info panel"><span class="material-icons-round">close</span></button>' +
        '<div id="memory-graph-info-content"></div>';
    wrap.appendChild(info);

    const loading = document.createElement('div');
    loading.id = 'memory-graph-loading';
    loading.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;gap:8px;flex-direction:column;';
    loading.innerHTML = '<div class="skeleton skeleton-text" style="width:60%"></div><div class="skeleton skeleton-text" style="width:40%"></div>';
    wrap.appendChild(loading);

    _graphInstance = new ForceGraph(canvas);

    // Resize observer — store ref so it can be disconnected in destroyMemoryGraph()
    const ro = new ResizeObserver(() => _graphInstance.resize());
    ro.observe(wrap);
    _graphInstance._resizeObserver = ro;

    // Search
    document.getElementById('memory-graph-search')?.addEventListener('input', (e) => {
        clearTimeout(e.target._debounce);
        e.target._debounce = setTimeout(() => _searchMemory(e.target.value, _graphInstance, container), 300);
    });

    // Refresh
    document.getElementById('memory-graph-refresh')?.addEventListener('click', () => _loadGraphData(_graphInstance, container));
    document.getElementById('memory-graph-close')?.addEventListener('click', () => {
        document.getElementById('memory-graph-info')?.classList.add('hidden');
    });

    await _loadGraphData(_graphInstance, container);
    _graphInstance.onNodeClick = (node) => _showNodeInfo(node, _graphInstance);
}

export function destroyMemoryGraph() {
    if (_graphInstance) {
        _graphInstance.stop();
        _graphInstance = null;
    }
}
