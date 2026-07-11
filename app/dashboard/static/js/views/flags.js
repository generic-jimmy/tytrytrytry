// Flagged messages queue
App.register('flags', (() => {
  let currentStatus = 'pending';

  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>Flagged Messages</h1>
        <p>Review borderline AI moderation calls. Mark as violation to log, dismiss if false positive.</p>
      </div>
      <div class="tabs" id="flag-tabs">
        <button class="tab ${currentStatus === 'pending' ? 'active' : ''}" data-status="pending">Pending</button>
        <button class="tab ${currentStatus === 'approved' ? 'active' : ''}" data-status="approved">Marked as violation</button>
        <button class="tab ${currentStatus === 'dismissed' ? 'active' : ''}" data-status="dismissed">Dismissed</button>
        <button class="tab ${currentStatus === 'all' ? 'active' : ''}" data-status="all">All</button>
      </div>
      <div id="flag-list"><div class="loading-state"><div class="spinner"></div><p>Loading…</p></div></div>
    `;

    container.querySelectorAll('#flag-tabs .tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        currentStatus = tab.dataset.status;
        container.querySelectorAll('#flag-tabs .tab').forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');
        loadList(container);
      });
    });

    await loadList(container);
  }

  async function loadList(container) {
    const gid = API.getGroup();
    const list = container.querySelector('#flag-list');
    list.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Loading…</p></div>`;
    try {
      const data = await API.listFlags(gid, currentStatus);
      if (data.flags.length === 0) {
        list.innerHTML = UI.emptyState('Nothing here', 'No flagged messages in this category.');
        return;
      }
      list.innerHTML = data.flags.map((f) => `
        <div class="flag-card ${f.severity}">
          <div class="fc-head">
            <div class="fc-meta">
              <span class="badge badge-${f.severity === 'high' ? 'danger' : f.severity === 'medium' ? 'warn' : 'info'}">${UI.escapeHTML(f.category)}</span>
              <span class="badge">${UI.escapeHTML(f.severity)}</span>
              <div class="confidence-meter">
                <span style="font-size:11px;color:var(--text-muted);">confidence</span>
                <div class="confidence-bar"><span style="width:${(f.confidence * 100).toFixed(0)}%"></span></div>
                <span class="mono" style="font-size:11px;">${(f.confidence * 100).toFixed(0)}%</span>
              </div>
              <span style="color:var(--text-dim);">·</span>
              <span class="mono">user ${f.user_id}</span>
              <span style="color:var(--text-dim);">·</span>
              <span style="color:var(--text-muted);">${UI.timeAgo(f.created_at)}</span>
            </div>
            ${f.status !== 'pending' ? `<span class="badge badge-info">${UI.escapeHTML(f.status)}</span>` : ''}
          </div>
          <div class="fc-text">${UI.escapeHTML(f.message_text)}</div>
          ${f.status === 'pending' ? `
            <div class="fc-actions">
              <button class="btn btn-danger btn-sm" data-id="${f.id}" data-decision="approve">Mark as violation</button>
              <button class="btn btn-ghost btn-sm" data-id="${f.id}" data-decision="dismiss">Dismiss</button>
            </div>
          ` : ''}
        </div>
      `).join('');

      list.querySelectorAll('button[data-decision]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const id = parseInt(btn.dataset.id, 10);
          const decision = btn.dataset.decision;
          try {
            await API.resolveFlag(gid, id, decision);
            UI.toast(decision === 'approve' ? 'Marked as violation' : 'Flag dismissed', 'success');
            loadList(container);
            App.refreshBadges();
          } catch (err) {
            UI.toast(`Failed: ${err.message}`, 'error');
          }
        });
      });
    } catch (err) {
      list.innerHTML = `<div class="empty-state"><h3>Failed to load</h3><p>${UI.escapeHTML(err.message)}</p></div>`;
    }
  }

  return { render };
})());
