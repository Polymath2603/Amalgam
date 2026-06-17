// webui/js/swarm.js
// Real-time agent swarm visualization using D3.js force-directed graph.
// Rendered in the Swarm tab. Updates via WebSocket events.
// Source: Wayland's Mission Control live panel concept.

class SwarmGraph {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) return;

        this.width = this.container.clientWidth;
        this.height = this.container.clientHeight || 400;

        this.STATUS_COLORS = {
            running: '#22c55e',
            waiting: '#eab308',
            done:    '#6b7280',
            failed:  '#ef4444',
        };

        this._initD3();
    }

    _initD3() {
        const svg = d3.select(`#${this.container.id}`)
            .append('svg')
            .attr('width', this.width)
            .attr('height', this.height);

        this.svg = svg;
        this.g = svg.append('g');

        svg.call(d3.zoom().on('zoom', (e) => {
            this.g.attr('transform', e.transform);
        }));

        this.sim = d3.forceSimulation()
            .force('link', d3.forceLink().id(d => d.id).distance(100))
            .force('charge', d3.forceManyBody().strength(-300))
            .force('center', d3.forceCenter(this.width / 2, this.height / 2));

        this.nodes = [];
        this.links = [];
    }

    update(data) {
        this.nodes = data.nodes;
        this.links = data.edges.map(e => ({ source: e.from, target: e.to }));
        this._render();
    }

    _render() {
        const link = this.g.selectAll('.link')
            .data(this.links, d => `${d.source}-${d.target}`)
            .join('line')
            .attr('class', 'link')
            .style('stroke', '#4b5563')
            .style('stroke-width', 1.5);

        const node = this.g.selectAll('.node')
            .data(this.nodes, d => d.id)
            .join('g')
            .attr('class', 'node')
            .call(d3.drag()
                .on('start', (e, d) => { if (!e.active) this.sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
                .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
                .on('end', (e, d) => { if (!e.active) this.sim.alphaTarget(0); d.fx = null; d.fy = null; })
            );

        node.selectAll('circle').data(d => [d])
            .join('circle')
            .attr('r', d => d.id === 'orchestrator' ? 20 : 14)
            .style('fill', d => this.STATUS_COLORS[d.status] || '#6b7280')
            .style('stroke', '#1f2937')
            .style('stroke-width', 2);

        node.selectAll('text').data(d => [d])
            .join('text')
            .attr('dy', 28)
            .attr('text-anchor', 'middle')
            .style('font-size', '11px')
            .style('fill', '#d1d5db')
            .text(d => d.label);

        node.on('mouseover', (e, d) => {
            const tip = document.getElementById('swarm-tooltip');
            if (tip) {
                tip.textContent = `${d.label} | ${d.status} | ${d.task || ''}`;
                tip.style.display = 'block';
                tip.style.left = e.pageX + 10 + 'px';
                tip.style.top = e.pageY + 'px';
            }
        }).on('mouseout', () => {
            const tip = document.getElementById('swarm-tooltip');
            if (tip) tip.style.display = 'none';
        });

        this.sim.nodes(this.nodes).on('tick', () => {
            link
                .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
            node.attr('transform', d => `translate(${d.x},${d.y})`);
        });
        this.sim.force('link').links(this.links);
        this.sim.alpha(0.3).restart();
    }
}

window.swarmGraph = null;

function initSwarmTab() {
    window.swarmGraph = new SwarmGraph('swarm-graph-container');
}

function handleSwarmUpdate(data) {
    if (window.swarmGraph) {
        window.swarmGraph.update(data);
        const isEmpty = data.nodes.length <= 1;
        const el = document.getElementById('swarm-empty');
        if (el) el.style.display = isEmpty ? 'block' : 'none';
    }
}
