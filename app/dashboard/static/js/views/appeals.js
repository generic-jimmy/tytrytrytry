// Appeals queue
App.register('appeals', (() => {
  let currentStatus = 'pending';

  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>Appeals</h1>
        <p>Users can appeal moderation actions against them via <code class="mono">/bappeal &lt;reason&gt;</code> in the group.</p>
      </div>
      <div class="tabs" id="appeal-tabs">
        <button class="tab ${currentStatus === 'pending' ? 'active' : ''}" data-status="pending">Pending</button>
        <button class="tab ${currentStatus === 'approved' ? 'active' : ''}" data-status="approved">Approved</button>
        <button class="tab ${currentStatus === 'denied' ? 'active' : ''}" data-status="denied">Denied</button>
        <button class="tab ${currentStatus === 'all' ? 'active' : ''}" data-status="all">All</button>
      </div>
      <div id="appeal-list"><div class="loading-state"><div class="spinner"></div><p>Loading…</p></div></div>
    `;

    container.querySelectorAll('#appeal-tabs .tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        currentStatus = tab.dataset.status;
        container.querySelectorAll('#appeal-tabs .tab').forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');
        loadList(container);
      });
    });

    await loadList(container);
  }

  async function loadList(container) {
    const gid = API.getGroup();
    const list = container.querySelector('#appeal-list');
    list.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Loading…</p></div>`;
    try {
      const data = await API.listAppeals(gid, currentStatus);
      if (data.appeals.length === 0) {
        list.innerHTML = UI.emptyState('No appeals', 'No appeals in this category.');
        return;
      }
      list.innerHTML = data.appeals.map((a) => `
        <div class="flag-card ${a.status === 'pending' ? 'medium' : 'low'}">
          <div class="fc-head">
            <div class="fc-meta">
              <span class="badge badge-${a.status === 'approved' ? 'success' : a.status === 'denied' ? 'danger' : 'warn'}">${UI.escapeHTML(a.status)}</span>
              <span class="badge badge-info">appealing: ${UI.escapeHTML(a.target_action)}</span>
              <span class="mono">user ${a.user_id}</span>
              <span style="color:var(--text-dim);">·</span>
              <span style="color:var(--text-muted);">${UI.timeAgo(a.created_at)}</span>
            </div>
          </div>
          <div class="fc-text">${UI.escapeHTML(a.reason)}</div>
          ${a.admin_note ? `<div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">Admin note: ${UI.escapeHTML(a.admin_note)}</div>` : ''}
          ${a.status === 'pending' ? `
            <div class="fc-actions">
              <button class="btn btn-success btn-sm" data-id="${a.id}" data-decision="approve">Approve (reverse action)</button>
              <button class="btn btn-danger btn-sm" data-id="${a.id}" data-decision="deny">Deny</button>
            </div>
          ` : ''}
        </div>
      `).join('');

      list.querySelectorAll('button[data-decision]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const id = parseInt(btn.dataset.id, 10);
          const decision = btn.dataset.decision;
          if (decision === 'deny') {
            resolveAppeal(id, decision, '');
            return;
          }
          // For approve, ask for optional note
          const m = UI.modal({
            title: 'Approve appeal',
            body: `
              <p style="color:var(--text-muted);font-size:13px;margin:0 0 12px;">Optionally add a note explaining the decision. Approving will attempt to reverse the original action (unban or unmute).</p>
              <textarea class="textarea" id="appeal-note" placeholder="Optional note…"></textarea>
            `,
            footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-success" data-confirm>Approve</button>`,
          });
          m.el.querySelector('[data-close]').addEventListener('click', m.close);
          m.el.querySelector('[data-confirm]').addEventListener('click', () => {
            const note = m.el.querySelector('#appeal-note').value.trim();
            m.close();
            resolveAppeal(id, decision, note);
          });
        });
      });
    } catch (err) {
      list.innerHTML = `<div class="empty-state"><h3>Failed to load</h3><p>${UI.escapeHTML(err.message)}</p></div>`;
    }
  }

  async function resolveAppeal(id, decision, note) {
    const gid = API.getGroup();
    try {
      await API.resolveAppeal(gid, id, decision, { note });
      UI.toast(`Appeal ${decision}d`, 'success');
      const container = document.getElementById('view-container');
      loadList(container);
      App.refreshBadges();
    } catch (err) {
      UI.toast(`Failed: ${err.message}`, 'error');
    }
  }

  return { render };
})());
