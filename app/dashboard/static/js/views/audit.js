// Audit trail — dashboard-driven changes
App.register('audit', (() => {
  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>Audit Trail</h1>
        <p>Every change made from this dashboard — who changed what and when.</p>
      </div>
      <div id="audit-list"><div class="loading-state"><div class="spinner"></div><p>Loading…</p></div></div>
    `;
    try {
      const data = await API.listAudit(gid, 200);
      const list = document.getElementById('audit-list');
      if (data.events.length === 0) {
        list.innerHTML = UI.emptyState('No audit events', 'Dashboard changes will appear here as they happen.');
        return;
      }
      list.innerHTML = `
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Action</th><th>Admin</th><th>Details</th><th>When</th></tr></thead>
            <tbody>
              ${data.events.map((e) => `
                <tr>
                  <td><span class="badge badge-accent">${UI.escapeHTML(e.action)}</span></td>
                  <td class="mono">${e.admin_id}</td>
                  <td class="mono" style="font-size:11px;">${UI.escapeHTML(e.details || '—')}</td>
                  <td class="mono" style="font-size:11px;color:var(--text-muted);">${UI.formatDateTime(e.created_at)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
    } catch (err) {
      document.getElementById('audit-list').innerHTML = UI.emptyState('Failed to load', err.message);
    }
  }

  return { render };
})());
