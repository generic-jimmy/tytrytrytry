// Analytics view — multi-chart breakdown
App.register('analytics', (() => {
  let chart1 = null, chart2 = null, chart3 = null;

  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>Analytics</h1>
        <p>Trends, distributions, and top contributors across your group.</p>
      </div>
      <div class="loading-state"><div class="spinner"></div><p>Loading analytics…</p></div>
    `;

    const [data7, data30] = await Promise.all([
      API.analytics(gid, 7),
      API.analytics(gid, 30),
    ]);

    const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#6c8cff';
    const accent2 = getComputedStyle(document.documentElement).getPropertyValue('--accent-2').trim() || '#8d6cff';
    const success = getComputedStyle(document.documentElement).getPropertyValue('--success').trim() || '#4ade80';
    const warn = getComputedStyle(document.documentElement).getPropertyValue('--warn').trim() || '#fbbf24';
    const danger = getComputedStyle(document.documentElement).getPropertyValue('--danger').trim() || '#f87171';
    const grid = getComputedStyle(document.documentElement).getPropertyValue('--border').trim() || '#232b3f';
    const muted = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim() || '#8b93a7';

    const sevColors = { high: danger, medium: warn, low: accent, none: muted };
    const sevData = data30.severity_distribution || {};
    const catData = data30.category_distribution || {};
    const actionData = data30.action_distribution || {};
    const topMembers = data30.top_members || [];

    const sevTotal = Object.values(sevData).reduce((a, b) => a + b, 0) || 1;
    const catTotal = Object.values(catData).reduce((a, b) => a + b, 0) || 1;
    const actionTotal = Object.values(actionData).reduce((a, b) => a + b, 0) || 1;

    container.innerHTML = `
      <div class="page-header">
        <h1>Analytics</h1>
        <p>Trends, distributions, and top contributors across your group.</p>
      </div>

      <div class="chart-card mb-6">
        <div class="chart-head">
          <h3>Activity · last 7 days</h3>
        </div>
        <div class="chart-container" style="height:320px;"><canvas id="trend-chart"></canvas></div>
      </div>

      <div class="analytics-grid">
        <div class="chart-card">
          <div class="chart-head"><h3>Flag severity distribution</h3><small class="text-muted">last 30 days</small></div>
          <div class="chart-container"><canvas id="sev-chart"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-head"><h3>Mod action distribution</h3><small class="text-muted">last 30 days</small></div>
          <div class="chart-container"><canvas id="action-chart"></canvas></div>
        </div>
      </div>

      <div class="analytics-grid" style="margin-top:20px;">
        <div class="chart-card">
          <div class="chart-head"><h3>Flag categories</h3></div>
          <div class="distribution-list">
            ${Object.keys(catData).length === 0
              ? '<div class="text-muted" style="padding:14px 0;">No flags recorded.</div>'
              : Object.entries(catData).sort((a, b) => b[1] - a[1]).map(([k, v]) => `
                <div class="distribution-row">
                  <div class="label-part">${UI.escapeHTML(k)}</div>
                  <div class="bar-part"><span style="width:${(v / catTotal * 100).toFixed(0)}%"></span></div>
                  <div class="count-part">${v}</div>
                </div>
              `).join('')}
          </div>
        </div>

        <div class="chart-card">
          <div class="chart-head"><h3>Top members</h3><small class="text-muted">by message count</small></div>
          ${topMembers.length === 0 ? UI.emptyState('No data yet', 'Member activity will appear once messages are sent.') : `
            <table class="table" style="background:transparent;border:none;">
              <tbody>
                ${topMembers.map((m, i) => `
                  <tr>
                    <td style="width:32px;"><strong style="color:var(--text-muted);">${i + 1}</strong></td>
                    <td>
                      <div class="member-cell">
                        <div class="avatar sm">${UI.escapeHTML(UI.initials(m.full_name || m.username || String(m.user_id)))}</div>
                        <div class="info">
                          <strong>${UI.escapeHTML(m.full_name || m.username || 'user')}</strong>
                          <small>${m.username ? '@' + UI.escapeHTML(m.username) : 'id ' + m.user_id}</small>
                        </div>
                      </div>
                    </td>
                    <td style="text-align:right;"><span class="badge">${UI.formatNumber(m.message_count)} msgs</span></td>
                    <td style="text-align:right;"><span class="reputation-pill ${m.reputation >= 0 ? 'positive' : 'negative'}">rep ${m.reputation}</span></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          `}
        </div>
      </div>
    `;

    // Trend chart - stacked bar of messages vs mod actions
    const trendCtx = document.getElementById('trend-chart').getContext('2d');
    if (chart1) chart1.destroy();
    chart1 = new Chart(trendCtx, {
      type: 'bar',
      data: {
        labels: data7.buckets.map((b) => new Date(b.hour).toLocaleString(undefined, { weekday: 'short', hour: '2-digit' })),
        datasets: [
          { label: 'Messages', data: data7.buckets.map((b) => b.messages), backgroundColor: accent + 'aa', borderRadius: 4 },
          { label: 'Mod actions', data: data7.buckets.map((b) => b.mod_actions), backgroundColor: danger + 'aa', borderRadius: 4 },
          { label: 'Flags', data: data7.buckets.map((b) => b.flags), backgroundColor: warn + 'aa', borderRadius: 4 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: muted, font: { size: 11 } } } },
        scales: {
          x: { stacked: true, grid: { color: grid, drawBorder: false }, ticks: { color: muted, font: { size: 9 }, maxTicksLimit: 14 } },
          y: { stacked: true, grid: { color: grid, drawBorder: false }, ticks: { color: muted, font: { size: 10 } }, beginAtZero: true },
        },
      },
    });

    // Severity pie
    const sevCtx = document.getElementById('sev-chart').getContext('2d');
    if (chart2) chart2.destroy();
    chart2 = new Chart(sevCtx, {
      type: 'doughnut',
      data: {
        labels: Object.keys(sevData),
        datasets: [{
          data: Object.values(sevData),
          backgroundColor: Object.keys(sevData).map((k) => sevColors[k] || accent),
          borderWidth: 0,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '60%',
        plugins: { legend: { position: 'bottom', labels: { color: muted, font: { size: 11 } } } },
      },
    });

    // Action pie
    const actCtx = document.getElementById('action-chart').getContext('2d');
    if (chart3) chart3.destroy();
    const palette = [accent, accent2, success, warn, danger, '#a78bfa', '#34d399', '#fbbf24'];
    chart3 = new Chart(actCtx, {
      type: 'doughnut',
      data: {
        labels: Object.keys(actionData),
        datasets: [{
          data: Object.values(actionData),
          backgroundColor: Object.keys(actionData).map((_, i) => palette[i % palette.length]),
          borderWidth: 0,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '60%',
        plugins: { legend: { position: 'bottom', labels: { color: muted, font: { size: 11 } } } },
      },
    });
  }

  return { render };
})());
