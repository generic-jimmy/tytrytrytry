// Mod log view
App.register('modlog', (() => {
  let currentAction = '';
  let offset = 0;
  const PAGE = 100;

  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>Moderation Log</h1>
        <p>Every moderation action taken by admins or automatically by the bot.</p>
      </div>
      <div class="members-toolbar">
        <select id="action-filter" class="select" style="width:auto;">
          <option value="">All actions</option>
          <option value="warn">Warn</option>
          <option value="mute">Mute</option>
          <option value="unmute">Unmute</option>
          <option value="kick">Kick</option>
          <option value="ban">Ban</option>
          <option value="unban">Unban</option>
          <option value="mute_flood">Mute (flood)</option>
          <option value="mute_warn_limit">Mute (warn limit)</option>
          <option value="delete">Delete</option>
          <option value="delete_and_ban">Delete + Ban</option>
          <option value="ban_bot">Ban bot</option>
          <option value="purgatory_approve">Purgatory approve</option>
          <option value="purgatory_deny">Purgatory deny</option>
          <option value="purgatory_ban">Purgatory ban</option>
        </select>
        <button class="btn btn-ghost btn-sm" id="prev-page" ${offset === 0 ? 'disabled' : ''}>← Prev</button>
        <button class="btn btn-ghost btn-sm" id="next-page">Next →</button>
      </div>
      <div id="modlog-list">${UI.skeleton(6)}</div>
    `;
    document.getElementById('action-filter').value = currentAction;
    document.getElementById('action-filter').addEventListener('change', (e) => {
      currentAction = e.target.value;
      offset = 0;
      loadList();
    });
    document.getElementById('prev-page').addEventListener('click', () => {
      offset = Math.max(0, offset - PAGE);
      loadList();
    });
    document.getElementById('next-page').addEventListener('click', () => {
      offset += PAGE;
      loadList();
    });

    await loadList();
  }

  async function loadList() {
    const gid = API.getGroup();
    const list = document.getElementById('modlog-list');
    if (!list) return;
    list.innerHTML = UI.skeleton(6);
    try {
      const data = await API.listModlog(gid, { action: currentAction, limit: PAGE, offset });
      if (data.logs.length === 0) {
        list.innerHTML = UI.emptyState('No logs', offset > 0 ? 'End of results.' : 'No moderation actions logged yet.');
        return;
      }
      list.innerHTML = `
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Action</th><th>Target user</th><th>Admin</th><th>Reason</th><th>When</th></tr></thead>
            <tbody>
              ${data.logs.map((l) => `
                <tr>
                  <td><span class="badge badge-${l.action.includes('ban') ? 'danger' : l.action.includes('mute') ? 'warn' : l.action.includes('approve') ? 'success' : 'info'}">${UI.escapeHTML(l.action)}</span></td>
                  <td class="mono">${l.target_user_id}</td>
                  <td class="mono">${l.admin_id || 'auto'}</td>
                  <td>${UI.escapeHTML(l.reason || '—')}</td>
                  <td class="mono" style="font-size:11px;color:var(--text-muted);">${UI.formatDateTime(l.created_at)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
        <p class="text-muted" style="font-size:12px;margin-top:8px;">Showing ${data.logs.length} of ${PAGE} per page · offset ${offset}</p>
      `;
      const prev = document.getElementById('prev-page');
      if (prev) prev.disabled = offset === 0;
    } catch (err) {
      list.innerHTML = `<div class="empty-state"><h3>Failed to load</h3><p>${UI.escapeHTML(err.message)}</p></div>`;
    }
  }

  return { render };
})());
