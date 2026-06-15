// Metrics dashboard — fetches and renders per-turn + tool analytics

export function loadMetrics() {
  const el = document.getElementById('metrics-dashboard');
  if (!el) return;
  el.innerHTML = '<p class="metrics-empty" data-i18n="metrics.loading">Loading...</p>';

  Promise.all([
    fetch('/api/metrics/summary').then(r => r.json()),
    fetch('/api/metrics/turns?limit=30').then(r => r.json()),
    fetch('/api/metrics/tool-history?limit=20').then(r => r.json()),
  ])
    .then(([summary, turns, tools]) => renderMetrics(el, summary, turns, tools))
    .catch(() => {
      el.innerHTML = `<p class="metrics-empty" data-i18n="metrics.no_data">No metrics yet — start chatting to see data.</p>`;
    });
}

function renderMetrics(el, summary, turns, tools) {
  const t = (key) => {
    const k = `metrics.${key}`;
    const el = document.querySelector(`[data-i18n="${k}"]`);
    if (el) return el.textContent;
    // fallback to en key
    const fallback = {
      turns: 'Turns', tokens: 'Tokens', cost: 'Cost',
      latency: 'Avg Latency', tool_calls: 'Tool Calls',
      errors: 'Errors', model: 'Model', total: 'Total',
      recent_turns: 'Recent Turns',
    };
    return fallback[key] || key;
  };

  const formatCost = (c) => {
    if (c < 0.001) return `$${(c * 1000).toFixed(4)}m`;
    return `$${c.toFixed(4)}`;
  };

  const formatTime = (ts) => {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString();
  };

  // --- Summary cards ---
  const sumCards = [
    { label: t('turns'), value: summary.total_turns ?? 0 },
    { label: t('tokens'), value: (summary.total_tokens ?? 0).toLocaleString() },
    { label: t('cost'), value: formatCost(summary.total_cost ?? 0) },
    { label: t('latency'), value: `${summary.avg_latency_ms ?? 0}ms` },
    { label: t('tool_calls'), value: summary.tool_calls ?? 0 },
    { label: t('errors'), value: summary.tool_failures ?? 0 },
  ];

  let html = '<div class="metrics-summary">';
  for (const c of sumCards) {
    html += `<div class="metric-card"><div class="metric-value">${c.value}</div><div class="metric-label">${c.label}</div></div>`;
  }
  html += '</div>';

  // --- Recent turns table ---
  const turnList = turns.turns ?? [];
  if (turnList.length) {
    html += `<div class="metrics-section-title">${t('recent_turns')}</div>`;
    html += '<table class="metrics-table"><thead><tr>';
    html += `<th>${t('total')}</th><th>${t('tokens')}</th><th>${t('latency')}</th><th>${t('cost')}</th><th>${t('model')}</th>`;
    html += '</tr></thead><tbody>';
    for (const turn of turnList) {
      html += `<tr><td>${formatTime(turn.timestamp)}</td><td>${turn.token_total.toLocaleString()}</td><td>${turn.latency_ms}ms</td><td>${formatCost(turn.cost)}</td><td>${turn.model || '-'}</td></tr>`;
    }
    html += '</tbody></table>';
  } else {
    html += `<p class="metrics-empty">${t('no_data')}</p>`;
  }

  el.innerHTML = html;
}

// Auto-refresh when tab becomes active
let metricsInterval = null;

export function initMetricsAutoRefresh() {
  const panel = document.getElementById('tab-metrics');
  if (!panel) return;

  const observer = new MutationObserver(() => {
    if (panel.classList.contains('active')) {
      loadMetrics();
      if (!metricsInterval) {
        metricsInterval = setInterval(loadMetrics, 10000);
      }
    } else {
      if (metricsInterval) {
        clearInterval(metricsInterval);
        metricsInterval = null;
      }
    }
  });
  observer.observe(panel, { attributes: true, attributeFilter: ['class'] });
}
