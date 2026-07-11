// Purgatory view — card grid with bulk actions
App.register('purgatory', (() => {
  let currentTab = 'pending';

  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>Purgatory</h1>
        <p>New members are muted until you approve, deny, or ban them.</p>
      </div>
      <div id="purgatory-body"><div class="loading-state"><div class="spinner"></div><p>Loading…</p></div></div>
    `;
    await loadTab(container);
  }

  async function loadTab(container) {
    const gid = API.getGroup();
    const body = container.querySelector('#purgatory-body');
    if (!body) return;
    body.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Loading…</p></div>`;
    try {
      const data = await API.listPurgatory(gid, currentTab);
      const counts = data.counts || {};
      const enabled = data.purgatory_enabled;

      body.innerHTML = `
        <div class="purgatory-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;flex-wrap:wrap;gap:12px;">
          <div class="stats-bar" style="display:flex;gap:8px;flex-wrap:wrap;">
            <span class="stat-pill ${currentTab === 'pending' ? 'badge-warn' : 'badge'}" style="padding:4px 12px;border-radius:999px;font-size:12px;cursor:pointer;" data-tab="pending">${counts.pending || 0} pending</span>
            <span class="stat-pill ${currentTab === 'suspicious' ? 'badge-danger' : 'badge'}" style="padding:4px 12px;border-radius:999px;font-size:12px;cursor:pointer;" data-tab="suspicious">${counts.suspicious || 0} suspicious</span>
            <span class="stat-pill ${currentTab === 'approved' ? 'badge-success' : 'badge'}" style="padding:4px 12px;border-radius:999px;font-size:12px;cursor:pointer;" data-tab="approved">${counts.approved || 0} approved</span>
            <span class="stat-pill ${currentTab === 'denied' ? 'badge-warn' : 'badge'}" style="padding:4px 12px;border-radius:999px;font-size:12px;cursor:pointer;" data-tab="denied">${counts.denied || 0} denied</span>
            <span class="stat-pill ${currentTab === 'banned' ? 'badge-danger' : 'badge'}" style="padding:4px 12px;border-radius:999px;font-size:12px;cursor:pointer;" data-tab="banned">${counts.banned || 0} banned</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;">
            <label class="toggle">
              <input type="checkbox" id="purgatory-toggle" ${enabled ? '' : 'checked'}>
              <span class="toggle-slider"></span>
            </label>
            <span style="font-size:12px;color:var(--text-muted);">${enabled ? 'Purgatory active' : 'Always allow (skipped)'}</span>
          </div>
        </div>

        ${data.entries.length === 0 ? UI.emptyState('No members in this category', 'New members will appear here when they join the group.') : `
          <div class="purgatory-cards">
            ${data.entries.map((e) => `
              <div class="purgatory-card ${e.status === 'suspicious' ? 'suspicious' : ''}" data-id="${e.id}">
                <div class="pc-head">
                  <div class="avatar">${UI.escapeHTML(UI.initials(e.full_name || e.username || String(e.user_id)))}</div>
                  <div class="pc-meta">
                    <strong>${UI.escapeHTML(e.full_name || 'user')}</strong>
                    <small>${e.username ? '@' + UI.escapeHTML(e.username) + ' · ' : ''}${e.user_id}</small>
                  </div>
                  ${e.status === 'suspicious' ? '<span class="badge badge-danger">suspicious</span>' : ''}
                </div>
                <div class="pc-details">
                  <div><span>Language</span><span>${UI.escapeHTML(e.language_code || '—')}</span></div>
                  <div><span>Premium</span><span>${e.is_premium ? 'Yes' : 'No'}</span></div>
                  <div><span>Joined</span><span>${UI.timeAgo(e.joined_at)}</span></div>
                  <div><span>Decided</span><span>${e.decided_at ? UI.timeAgo(e.decided_at) : '—'}</span></div>
                </div>
                ${['pending', 'suspicious'].includes(e.status) ? `
                  <div class="pc-actions">
                    <button class="btn btn-success btn-sm" data-decision="approve">Approve</button>
                    <button class="btn btn-ghost btn-sm" data-decision="deny">Deny</button>
                    <button class="btn btn-danger btn-sm" data-decision="ban">Ban</button>
                  </div>
                ` : `<div style="text-align:center;font-size:12px;color:var(--text-muted);padding:6px;">Resolved</div>`}
              </div>
            `).join('')}
          </div>
        `}
      `;

      body.querySelectorAll('span[data-tab]').forEach((pill) => {
        pill.addEventListener('click', () => {
          currentTab = pill.dataset.tab;
          loadTab(container);
        });
      });

      body.querySelectorAll('button[data-decision]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const card = btn.closest('.purgatory-card');
          const entryId = parseInt(card.dataset.id, 10);
          const decision = btn.dataset.decision;
          const verb = { approve: 'Approve', deny: 'Deny', ban: 'Ban' }[decision];
          UI.confirmModal({
            title: `${verb} member?`,
            message: `Are you sure you want to ${decision} this member?`,
            confirmText: verb,
            danger: decision === 'ban',
            onConfirm: async () => {
              try {
                await API.decidePurgatory(gid, entryId, decision);
                UI.toast(`Member ${decision}d`, 'success');
                loadTab(container);
                App.refreshBadges();
              } catch (err) {
                UI.toast(`Failed: ${err.message}`, 'error');
              }
            },
          });
        });
      });

      const toggle = body.querySelector('#purgatory-toggle');
      if (toggle) {
        toggle.addEventListener('change', async () => {
          const alwaysAllow = !toggle.checked; // if not checked = purgatory active, so always_allow = !purgatory
          try {
            await API.togglePurgatory(gid, alwaysAllow);
            UI.toast(alwaysAllow ? 'Purgatory disabled — new members join normally' : 'Purgatory enabled', 'success');
          } catch (err) {
            UI.toast(`Failed: ${err.message}`, 'error');
            toggle.checked = !toggle.checked;
          }
        });
      }
    } catch (err) {
      body.innerHTML = `<div class="empty-state"><h3>Failed to load</h3><p>${UI.escapeHTML(err.message)}</p></div>`;
    }
  }

  return { render };
})());
