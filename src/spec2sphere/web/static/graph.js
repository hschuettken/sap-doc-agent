/* SAP Doc Agent — Dependency Graph (vis.js) */

const TYPE_COLORS = {
    view: { background: '#dbeafe', border: '#3b82f6', font: '#1e40af' },
    adso: { background: '#dcfce7', border: '#22c55e', font: '#166534' },
    transformation: { background: '#ffedd5', border: '#f97316', font: '#9a3412' },
    table: { background: '#f3e8ff', border: '#a855f7', font: '#6b21a8' },
    class: { background: '#fef3c7', border: '#f59e0b', font: '#92400e' },
    process_chain: { background: '#fce7f3', border: '#ec4899', font: '#9d174d' },
};
const DEFAULT_COLOR = { background: '#f1f5f9', border: '#94a3b8', font: '#475569' };

let network = null;
let allNodes = [];
let allEdges = [];

function initGraph() {
    if (!graphData || !graphData.nodes) return;

    const connectionCount = {};
    (graphData.edges || []).forEach(e => {
        connectionCount[e.source] = (connectionCount[e.source] || 0) + 1;
        connectionCount[e.target] = (connectionCount[e.target] || 0) + 1;
    });

    allNodes = graphData.nodes.map(n => {
        const colors = TYPE_COLORS[n.type] || DEFAULT_COLOR;
        const conns = connectionCount[n.id] || 0;
        return {
            id: n.id,
            label: n.name || n.id,
            color: colors,
            font: { color: colors.font, size: 12 },
            size: 15 + Math.min(conns * 3, 25),
            shape: 'dot',
            _type: n.type,
            _layer: n.layer || '',
            _source: n.source_system || '',
            _name: n.name || n.id,
        };
    });

    allEdges = (graphData.edges || []).map((e, i) => ({
        id: 'e' + i,
        from: e.source,
        to: e.target,
        label: e.type,
        arrows: 'to',
        color: { color: '#94a3b8', highlight: '#05415A' },
        font: { size: 9, color: '#9ca3af', strokeWidth: 0 },
    }));

    // Populate filters
    const types = [...new Set(allNodes.map(n => n._type))].sort();
    const layers = [...new Set(allNodes.map(n => n._layer).filter(Boolean))].sort();
    const typeSelect = document.getElementById('graph-type-filter');
    const layerSelect = document.getElementById('graph-layer-filter');
    types.forEach(t => { const o = document.createElement('option'); o.value = t; o.text = t; typeSelect.add(o); });
    layers.forEach(l => { const o = document.createElement('option'); o.value = l; o.text = l; layerSelect.add(o); });

    renderGraph(allNodes, allEdges);

    // Filter listeners
    typeSelect.addEventListener('change', applyFilters);
    layerSelect.addEventListener('change', applyFilters);
    document.getElementById('graph-search').addEventListener('input', applyFilters);
}

function renderGraph(nodes, edges) {
    const container = document.getElementById('graph-container');
    const data = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
    const options = {
        physics: { stabilization: { iterations: 150 }, barnesHut: { gravitationalConstant: -3000, springLength: 150 } },
        interaction: { hover: true, tooltipDelay: 200 },
        layout: { improvedLayout: true },
    };
    network = new vis.Network(container, data, options);

    network.on('click', function(params) {
        if (params.nodes.length > 0) {
            const nodeId = params.nodes[0];
            const node = allNodes.find(n => n.id === nodeId);
            if (node) showPanel(node);
        } else {
            document.getElementById('node-panel').style.display = 'none';
        }
    });

    network.on('doubleClick', function(params) {
        if (params.nodes.length > 0) {
            window.location.href = '/ui/objects/' + params.nodes[0];
        }
    });
}

function showPanel(node) {
    document.getElementById('panel-name').textContent = node._name;
    document.getElementById('panel-id').textContent = node.id;
    document.getElementById('panel-details').innerHTML = `
        <div><span class="text-gray-400">Type:</span> ${node._type}</div>
        <div><span class="text-gray-400">Layer:</span> ${node._layer || '—'}</div>
        <div><span class="text-gray-400">Source:</span> ${node._source || '—'}</div>
    `;
    document.getElementById('panel-link').href = '/ui/objects/' + node.id;
    document.getElementById('node-panel').style.display = 'block';
}

function applyFilters() {
    const typeFilter = document.getElementById('graph-type-filter').value;
    const layerFilter = document.getElementById('graph-layer-filter').value;
    const search = document.getElementById('graph-search').value.toLowerCase();

    let nodes = allNodes;
    if (typeFilter) nodes = nodes.filter(n => n._type === typeFilter);
    if (layerFilter) nodes = nodes.filter(n => n._layer === layerFilter);
    if (search) nodes = nodes.filter(n => n._name.toLowerCase().includes(search) || n.id.toLowerCase().includes(search));

    const nodeIds = new Set(nodes.map(n => n.id));
    const edges = allEdges.filter(e => nodeIds.has(e.from) && nodeIds.has(e.to));
    renderGraph(nodes, edges);
}

function resetGraph() {
    document.getElementById('graph-type-filter').value = '';
    document.getElementById('graph-layer-filter').value = '';
    document.getElementById('graph-search').value = '';
    renderGraph(allNodes, allEdges);
}

// Focus on a specific node (from URL param)
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('focus')) {
    document.addEventListener('DOMContentLoaded', () => {
        setTimeout(() => {
            const focusId = urlParams.get('focus');
            if (network) {
                network.selectNodes([focusId]);
                network.focus(focusId, { scale: 1.5, animation: true });
                const node = allNodes.find(n => n.id === focusId);
                if (node) showPanel(node);
            }
        }, 1000);
    });
}

initGraph();
