// Members view — searchable list with profile drawer
App.register('members', (() => {
  let currentQuery = '';
  let currentStatus = '';

  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>Members</h1>
        <p>Search, filter, and manage individual members. Click a row for full history.</p>
      </div>
      <div class="members-toolbar">
        <div class="search">
          <svg viewBox="0 0 24 24" width="16" height="16"><path d="M15.5 14h-.79l-.28-.27a6.5 6.5 0 1 0-.7.7l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z" fill="currentColor"/></svg>
          <input type="text" id="member-search" placeholder="Search by name, username, or ID…" value="${UI.escapeHTML(currentQuery)}">
        </div>
        <select id="member-status" class="select" style="width:auto;">
          <option value="">All</option>
          <option value="muted" ${currentStatus === 'muted' ? 'selected' : ''}>Muted</option>
          <option value="banned" ${currentStatus === 'banned' ? 'selected' : ''}>Banned</option>
          <option value="warned" ${currentStatus === 'warned' ? 'selected' : ''}>Warned</option>
        </select>
      </div>
      <div id="member-list-container">${UI.skeleton(6)}</div>
    `;

    const searchInput = document.getElementById('member-search');
    searchInput.addEventListener('input', UI.debounce((e) => {
      currentQuery = e.target.value;
      loadList();
    }, 250));
    document.getElementById('member-status').addEventListener('change', (e) => {
      currentStatus = e.target.value;
      loadList();
    });

    async function loadList() {
      const listEl = document.getElementById('member-list-container');
      listEl.innerHTML = UI.skeleton(6);
      try {
        const data = await API.listMembers(gid, { q: currentQuery, status: currentStatus, limit: 100 });
        if (data.members.length === 0) {
          listEl.innerHTML = UI.emptyState('No members', 'No members match your filters.');
          return;
        }
        listEl.innerHTML = `
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr><th>Member</th><th>ID</th><th>Reputation</th><th>Messages</th><th>Warns</th><th>Status</th><th>Last active</th><th></th></tr>
              </thead>
              <tbody>
                ${data.members.map((m) => `
                  <tr data-user-id="${m.user_id}">
                    <td>
                      <div class="member-cell">
                        <div class="avatar sm">${UI.escapeHTML(UI.initials(m.full_name || m.username || String(m.user_id)))}</div>
                        <div class="info">
                          <strong>${UI.escapeHTML(m.full_name || 'user')}</strong>
                          <small>${m.username ? '@' + UI.escapeHTML(m.username) : ''}</small>
                        </div>
                      </div>
                    </td>
                    <td class="mono">${m.user_id}</td>
                    <td><span class="reputation-pill ${m.reputation > 0 ? 'positive' : m.reputation < 0 ? 'negative' : ''}">${m.reputation}</span></td>
                    <td>${UI.formatNumber(m.message_count)}</td>
                    <td>${m.warn_count || 0}</td>
                    <td>
                      ${m.is_banned ? '<span class="badge badge-danger">banned</span>' : ''}
                      ${m.is_muted ? '<span class="badge badge-warn">muted</span>' : ''}
                      ${!m.is_banned && !m.is_muted ? '<span class="badge badge-success">active</span>' : ''}
                    </td>
                    <td class="mono" style="font-size:11px;color:var(--text-muted);">${UI.timeAgo(m.last_active)}</td>
                    <td><button class="btn btn-ghost btn-sm" data-view="${m.user_id}">View</button></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
          <p class="text-muted" style="font-size:12px;margin-top:8px;">Showing ${data.members.length} of ${data.total} members</p>
        `;
        listEl.querySelectorAll('button[data-view]').forEach((btn) => {
          btn.addEventListener('click', () => openProfile(parseInt(btn.dataset.view, 10)));
        });
        listEl.querySelectorAll('tr[data-user-id]').forEach((tr) => {
          tr.addEventListener('click', (e) => {
            if (e.target.closest('button')) return;
            openProfile(parseInt(tr.dataset.userId, 10));
          });
        });
      } catch (err) {
        listEl.innerHTML = `<div class="empty-state"><h3>Failed to load</h3><p>${UI.escapeHTML(err.message)}</p></div>`;
      }
    }

    loadList();
  }

  async function openProfile(userId) {
    const gid = API.getGroup();
    const drawer = UI.drawer({ title: 'Member profile', body: UI.skeleton(4) });
    try {
      const data = await API.memberDetail(gid, userId);
      const p = data.profile;
      drawer.el.querySelector('.drawer-body').innerHTML = `
        <div style="display:flex;align-items:center;gap:14px;margin-bottom:20px;">
          <div class="avatar lg">${UI.escapeHTML(UI.initials(p.full_name || p.username || String(p.user_id)))}</div>
          <div>
            <h3 style="margin:0 0 4px;font-size:18px;">${UI.escapeHTML(p.full_name || 'user')}</h3>
            ${p.username ? `<div style="color:var(--text-muted);font-size:13px;">@${UI.escapeHTML(p.username)}</div>` : ''}
            <div style="color:var(--text-dim);font-size:11px;font-family:var(--font-mono);margin-top:2px;">${p.user_id}</div>
          </div>
        </div>

        <div class="grid-3" style="margin-bottom:20px;">
          <div style="text-align:center;padding:10px;background:var(--surface-2);border-radius:8px;">
            <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;">Reputation</div>
            <div style="font-size:20px;font-weight:700;color:${p.reputation >= 0 ? 'var(--success)' : 'var(--danger)'};">${p.reputation}</div>
          </div>
          <div style="text-align:center;padding:10px;background:var(--surface-2);border-radius:8px;">
            <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;">Messages</div>
            <div style="font-size:20px;font-weight:700;">${UI.formatNumber(p.message_count)}</div>
          </div>
          <div style="text-align:center;padding:10px;background:var(--surface-2);border-radius:8px;">
            <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;">Warns</div>
            <div style="font-size:20px;font-weight:700;color:var(--warn);">${p.warn_count}</div>
          </div>
        </div>

        <div style="display:flex;gap:6px;margin-bottom:20px;flex-wrap:wrap;">
          ${p.is_muted
            ? `<button class="btn btn-success btn-sm" data-action="unmute">Unmute</button>`
            : `<button class="btn btn-warn btn-sm" data-action="mute">Mute</button>`}
          ${p.is_banned
            ? `<button class="btn btn-success btn-sm" data-action="unban">Unban</button>`
            : `<button class="btn btn-danger btn-sm" data-action="ban">Ban</button>`}
          <button class="btn btn-ghost btn-sm" data-action="reset_reputation">Reset reputation</button>
        </div>

        <h4 style="font-size:13px;margin:0 0 10px;">Recent warnings</h4>
        ${data.warns.length === 0 ? '<p class="text-muted" style="font-size:12px;">No warnings.</p>' : `
          <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:20px;">
            ${data.warns.map((w) => `
              <div style="padding:8px 10px;background:var(--surface-2);border-radius:6px;font-size:12px;">
                <div style="color:var(--text-muted);font-size:11px;">${UI.formatDateTime(w.created_at)}</div>
                <div>${UI.escapeHTML(w.reason || '—')}</div>
              </div>
            `).join('')}
          </div>
        `}

        <h4 style="font-size:13px;margin:0 0 10px;">Moderation history</h4>
        ${data.mod_actions.length === 0 ? '<p class="text-muted" style="font-size:12px;">No moderation actions.</p>' : `
          <div style="display:flex;flex-direction:column;gap:6px;">
            ${data.mod_actions.map((m) => `
              <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 10px;background:var(--surface-2);border-radius:6px;font-size:12px;">
                <div>
                  <span class="badge badge-${m.action.includes('ban') ? 'danger' : m.action.includes('mute') ? 'warn' : 'info'}">${UI.escapeHTML(m.action)}</span>
                  <span style="margin-left:8px;color:var(--text-muted);">${UI.escapeHTML(m.reason || '')}</span>
                </div>
                <span style="color:var(--text-dim);font-size:11px;">${UI.timeAgo(m.created_at)}</span>
              </div>
            `).join('')}
          </div>
        `}
      `;

      drawer.el.querySelectorAll('button[data-action]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const action = btn.dataset.action;
          const verb = { mute: 'Mute', unmute: 'Unmute', ban: 'Ban', unban: 'Unban', reset_reputation: 'Reset reputation for' }[action];
          UI.confirmModal({
            title: `${verb} user?`,
            message: `Are you sure you want to ${action.replace('_', ' ')} ${p.full_name || p.user_id}?`,
            confirmText: verb,
            danger: ['ban', 'mute', 'reset_reputation'].includes(action),
            onConfirm: async () => {
              try {
                await API.memberAction(gid, userId, action);
                UI.toast(`${verb} applied`, 'success');
                drawer.close();
                App.renderView('members');
              } catch (err) {
                UI.toast(`Failed: ${err.message}`, 'error');
              }
            },
          });
        });
      });
    } catch (err) {
      drawer.el.querySelector('.drawer-body').innerHTML = UI.emptyState('Failed to load', err.message);
    }
  }

  return { render };
})());
