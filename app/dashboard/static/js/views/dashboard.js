// Dashboard view — overview stats, activity chart, recent actions
App.register('dashboard', (() => {
  let chart = null;

  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>Dashboard</h1>
        <p>Real-time overview of your group's activity and moderation pipeline.</p>
      </div>
      <div class="loading-state"><div class="spinner"></div><p>Loading overview…</p></div>
    `;
    const data = await API.overview(gid);

    const s = data.stats;
    container.innerHTML = `
      <div class="page-header">
        <h1>Dashboard</h1>
        <p>Real-time overview of your group's activity and moderation pipeline.</p>
      </div>

      <div class="cards-grid">
        <div class="card stat-card elevated card-glow info">
          <div class="stat-icon"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-2 12H6v-2h12v2zm0-3H6V9h12v2zm0-3H6V6h12v2z" fill="currentColor"/></svg></div>
          <div class="stat-label">Messages (24h)</div>
          <div class="stat-value">${UI.formatNumber(s.messages_24h)}</div>
          <div class="stat-delta">${s.ai_calls || 0} AI checks</div>
        </div>

        <div class="card stat-card elevated success">
          <div class="stat-icon"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5z" fill="currentColor"/></svg></div>
          <div class="stat-label">Total Members</div>
          <div class="stat-value">${UI.formatNumber(s.total_members)}</div>
          <div class="stat-delta up">+${s.new_members_24h} today</div>
        </div>

        <div class="card stat-card elevated warn">
          <div class="stat-icon"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M14.4 6L14 4H5v17h2v-7h5.6l.4 2h7V6z" fill="currentColor"/></svg></div>
          <div class="stat-label">Pending Reviews</div>
          <div class="stat-value">${UI.formatNumber(s.pending_flags)}</div>
          <div class="stat-delta">${s.pending_purgatory} in purgatory</div>
        </div>

        <div class="card stat-card elevated danger">
          <div class="stat-icon"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M12 2L1 21h22L12 2zm0 3.45l8.27 14.3H3.73L12 5.45zM11 16h2v2h-2v-2zm0-6h2v4h-2v-4z" fill="currentColor"/></svg></div>
          <div class="stat-label">Mod Actions (24h)</div>
          <div class="stat-value">${UI.formatNumber(s.mod_actions_24h)}</div>
          <div class="stat-delta">${s.muted_count} muted · ${s.banned_count} banned</div>
        </div>
      </div>

      <div class="dashboard-grid">
        <div class="chart-card">
          <div class="chart-head">
            <h3>Activity · last 24 hours</h3>
            <div class="chart-tabs">
              <button class="chart-tab active" data-metric="messages">Messages</button>
              <button class="chart-tab" data-metric="mod_actions">Mod</button>
              <button class="chart-tab" data-metric="ai_calls">AI Calls</button>
            </div>
          </div>
          <div class="chart-container"><canvas id="activity-chart"></canvas></div>
        </div>

        <div class="chart-card">
          <div class="chart-head">
            <h3>Recent actions</h3>
            <a href="#/modlog" class="btn btn-ghost btn-sm">View all</a>
          </div>
          <div class="recent-list" id="recent-list">
            ${data.recent_actions.length === 0 ? UI.emptyState('No actions yet', 'Moderation events will appear here as they happen.') : ''}
            ${data.recent_actions.map((a) => `
              <div class="list-item">
                <div class="avatar sm">${UI.escapeHTML((a.action || '?')[0].toUpperCase())}</div>
                <div class="meta">
                  <strong>${UI.escapeHTML(a.action)}</strong>
                  <small>user ${a.target_user_id}${a.reason ? ' · ' + UI.escapeHTML(a.reason.slice(0, 60)) : ''}</small>
                </div>
                <div class="time">${UI.timeAgo(a.created_at)}</div>
              </div>
            `).join('')}
          </div>
        </div>
      </div>

      <div style="margin-top:24px;">
        <div class="section-header">
          <h2>Quick actions</h2>
        </div>
        <div class="cards-grid">
          <div class="action-card" data-route="#/ai">
            <div class="ac-icon"><svg viewBox="0 0 24 24" width="20" height="20"><path d="M21 10.12h-6.78l2.74-2.82-2.2-2.2L9 10.9V3H7v6.88L2.98 5.86l-2.2 2.2L5.56 12H3v2h2.56l-2.78 2.74 2.2 2.2L7 14.12V21h2v-6.09l3.49 3.5 2.2-2.2-3.34-3.21H21v-2.88z" fill="currentColor"/></svg></div>
            <h4>Tune AI moderation</h4>
            <p>Adjust model, thresholds, and prompts</p>
          </div>
          <div class="action-card" data-route="#/automation">
            <div class="ac-icon"><svg viewBox="0 0 24 24" width="20" height="20"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 14H7v-2h5v2zm5-4H7v-2h10v2zm0-4H7V7h10v2z" fill="currentColor"/></svg></div>
            <h4>Set up rules</h4>
            <p>Create custom commands and auto-responses</p>
          </div>
          <div class="action-card" data-route="#/purgatory">
            <div class="ac-icon"><svg viewBox="0 0 24 24" width="20" height="20"><path d="M12 2L4 5v6c0 5.55 3.84 10.74 8 12 4.16-1.26 8-6.45 8-12V5l-8-3z" fill="currentColor"/></svg></div>
            <h4>Review purgatory</h4>
            <p>${s.pending_purgatory} new members awaiting approval</p>
          </div>
          <div class="action-card" data-route="#/analytics">
            <div class="ac-icon"><svg viewBox="0 0 24 24" width="20" height="20"><path d="M3 3v18h18v-2H5V3H3zm14 14V8h-2v9h2zm-4 0V5h-2v12h2zm-4 0V11H7v6h2z" fill="currentColor"/></svg></div>
            <h4>View analytics</h4>
            <p>Deep dive into trends and patterns</p>
          </div>
        </div>
      </div>
    `;

    renderActivityChart(data.activity);

    container.querySelectorAll('.action-card[data-route]').forEach((card) => {
      card.addEventListener('click', () => { window.location.hash = card.dataset.route; });
    });

    container.querySelectorAll('.chart-tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        container.querySelectorAll('.chart-tab').forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');
        renderActivityChart(data.activity, tab.dataset.metric);
      });
    });
  }

  function renderActivityChart(activity, metric = 'messages') {
    const canvas = document.getElementById('activity-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (chart) chart.destroy();

    const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#6c8cff';
    const grid = getComputedStyle(document.documentElement).getPropertyValue('--border').trim() || '#232b3f';
    const muted = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim() || '#8b93a7';

    const gradient = ctx.createLinearGradient(0, 0, 0, 280);
    gradient.addColorStop(0, accent + '66');
    gradient.addColorStop(1, accent + '00');

    chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: activity.map((b) => b.hour),
        datasets: [{
          label: metric.replace('_', ' '),
          data: activity.map((b) => b[metric] || 0),
          borderColor: accent,
          backgroundColor: gradient,
          fill: true,
          tension: 0.35,
          pointRadius: 0,
          pointHoverRadius: 5,
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: grid, drawBorder: false }, ticks: { color: muted, maxTicksLimit: 8, font: { size: 10 } } },
          y: { grid: { color: grid, drawBorder: false }, ticks: { color: muted, font: { size: 10 } }, beginAtZero: true },
        },
        interaction: { mode: 'index', intersect: false },
      },
    });
  }

  return { render };
})());
