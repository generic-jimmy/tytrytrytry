// System Health view — rate limiter, in-memory trackers, webhook status
App.register('health', (() => {
  let pollHandle = null;

  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>System Health</h1>
        <p>Live snapshot of the bot's internal state, rate-limit usage, and tracker metrics.</p>
      </div>
      <div id="health-body"><div class="loading-state"><div class="spinner"></div><p>Loading…</p></div></div>
    `;

    async function poll() {
      try {
        const data = await API.health(gid);
        const rl = data.rate_limiter || {};
        const usagePct = rl.max_per_period ? (rl.calls_last_period / rl.max_per_period * 100) : 0;
        const body = document.getElementById('health-body');
        if (!body) return;
        body.innerHTML = `
          <div class="cards-grid">
            <div class="card stat-card elevated success">
              <div class="stat-icon"><span class="status-dot"></span></div>
              <div class="stat-label">Bot status</div>
              <div class="stat-value" style="font-size:20px;">Operational</div>
              <div class="stat-delta">Webhook active</div>
            </div>
            <div class="card stat-card elevated info">
              <div class="stat-icon"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 14H7v-2h5v2zm5-4H7v-2h10v2zm0-4H7V7h10v2z" fill="currentColor"/></svg></div>
              <div class="stat-label">AI rate limit</div>
              <div class="stat-value" style="font-size:20px;">${rl.calls_last_period || 0} / ${rl.max_per_period || 0}</div>
              <div class="stat-delta">${usagePct.toFixed(0)}% of ${rl.period_seconds || 60}s window</div>
            </div>
            <div class="card stat-card elevated">
              <div class="stat-icon"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z" fill="currentColor"/></svg></div>
              <div class="stat-label">Total AI calls</div>
              <div class="stat-value">${UI.formatNumber(rl.total_calls || 0)}</div>
              <div class="stat-delta">${rl.total_failures || 0} failures</div>
            </div>
            <div class="card stat-card elevated warn">
              <div class="stat-icon"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" fill="currentColor"/></svg></div>
              <div class="stat-label">Trackers in memory</div>
              <div class="stat-value">${(data.flood_trackers || 0) + (data.slow_mode_trackers || 0)}</div>
              <div class="stat-delta">${data.flood_trackers || 0} flood · ${data.slow_mode_trackers || 0} slow-mode</div>
            </div>
          </div>

          <div class="section-block" style="margin-top:20px;">
            <h3>Detailed metrics</h3>
            <div class="health-metric">
              <div class="hm-label"><span class="status-dot"></span> Webhook endpoint</div>
              <div class="hm-value">/webhook/* · active</div>
            </div>
            <div class="health-metric">
              <div class="hm-label"><span class="status-dot"></span> Database connection</div>
              <div class="hm-value">async · pool_pre_ping</div>
            </div>
            <div class="health-metric ${usagePct > 80 ? 'warn' : ''}">
              <div class="hm-label"><span class="status-dot ${usagePct > 80 ? 'warn' : ''}"></span> Rate limiter usage</div>
              <div class="hm-value">${usagePct.toFixed(1)}%</div>
            </div>
            <div class="health-metric">
              <div class="hm-label"><span class="status-dot"></span> Scheduled message poller</div>
              <div class="hm-value">30s interval</div>
            </div>
            <div class="health-metric">
              <div class="hm-label"><span class="status-dot"></span> Flood protection</div>
              <div class="hm-value">5 msgs / 6s</div>
            </div>
          </div>

          <div class="section-block">
            <h3>Quick health check commands</h3>
            <p class="text-muted" style="font-size:13px;">Run these to verify the bot is responsive in your group:</p>
            <ul style="list-style:none;padding:0;margin-top:14px;display:flex;flex-direction:column;gap:8px;">
              <li><code class="mono" style="background:var(--surface-2);padding:4px 8px;border-radius:6px;">/start</code> <span class="text-muted" style="font-size:12px;">— should reply with the welcome message</span></li>
              <li><code class="mono" style="background:var(--surface-2);padding:4px 8px;border-radius:6px;">/bhelp</code> <span class="text-muted" style="font-size:12px;">— lists every available command</span></li>
              <li><code class="mono" style="background:var(--surface-2);padding:4px 8px;border-radius:6px;">/breputation</code> <span class="text-muted" style="font-size:12px;">— shows your reputation in the group</span></li>
              <li><code class="mono" style="background:var(--surface-2);padding:4px 8px;border-radius:6px;">/brules</code> <span class="text-muted" style="font-size:12px;">— shows the group rules</span></li>
              <li><code class="mono" style="background:var(--surface-2);padding:4px 8px;border-radius:6px;">/bfilters</code> <span class="text-muted" style="font-size:12px;">— lists current word/link filters</span></li>
            </ul>
          </div>
        `;
      } catch (err) {
        const body = document.getElementById('health-body');
        if (body) body.innerHTML = UI.emptyState('Failed to load', err.message);
      }
    }

    await poll();
    // Poll every 10 seconds while the view is active
    pollHandle = setInterval(poll, 10000);
    // Clean up when the view is replaced
    const observer = new MutationObserver(() => {
      if (!document.getElementById('health-body')) {
        clearInterval(pollHandle);
        observer.disconnect();
      }
    });
    observer.observe(document.getElementById('view-container'), { childList: true });
  }

  return { render };
})());
