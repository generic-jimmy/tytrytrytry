// Filters view
App.register('filters', (() => {
  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>Filters</h1>
        <p>Word and link blocklist. Matching messages are deleted immediately — before any AI check.</p>
      </div>

      <div class="section-block">
        <h3>Add filter</h3>
        <div class="field-row">
          <div class="field" style="max-width:140px;">
            <label class="label">Type</label>
            <select class="select" id="filter-type">
              <option value="word">word</option>
              <option value="link">link</option>
            </select>
          </div>
          <div class="field" style="flex:1;">
            <label class="label">Pattern</label>
            <input class="input" id="filter-pattern" placeholder="badword or https://spam.example">
          </div>
        </div>
        <button class="btn" id="add-filter">Add filter</button>
      </div>

      <div class="section-block">
        <h3>Active filters</h3>
        <div id="filter-list"><div class="loading-state"><div class="spinner"></div><p>Loading…</p></div></div>
      </div>
    `;

    document.getElementById('add-filter').addEventListener('click', async () => {
      const type = document.getElementById('filter-type').value;
      const pattern = document.getElementById('filter-pattern').value.trim();
      if (!pattern) { UI.toast('Pattern is required', 'info'); return; }
      try {
        await API.addFilter(gid, { type, pattern });
        UI.toast('Filter added', 'success');
        document.getElementById('filter-pattern').value = '';
        loadList();
      } catch (err) {
        UI.toast(`Failed: ${err.message}`, 'error');
      }
    });

    await loadList();
  }

  async function loadList() {
    const gid = API.getGroup();
    const list = document.getElementById('filter-list');
    if (!list) return;
    list.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Loading…</p></div>`;
    try {
      const data = await API.listFilters(gid);
      if (data.filters.length === 0) {
        list.innerHTML = UI.emptyState('No filters', 'Add one above to start blocking patterns.');
        return;
      }
      list.innerHTML = `
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Type</th><th>Pattern</th><th></th></tr></thead>
            <tbody>
              ${data.filters.map((f) => `
                <tr>
                  <td><span class="badge badge-${f.type === 'link' ? 'info' : 'accent'}">${UI.escapeHTML(f.type)}</span></td>
                  <td class="mono">${UI.escapeHTML(f.pattern)}</td>
                  <td style="text-align:right;"><button class="btn btn-danger btn-sm" data-del="${f.id}">Delete</button></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;

      list.querySelectorAll('button[data-del]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const id = parseInt(btn.dataset.del, 10);
          try {
            await API.deleteFilter(gid, id);
            UI.toast('Filter deleted', 'success');
            loadList();
          } catch (err) {
            UI.toast(`Failed: ${err.message}`, 'error');
          }
        });
      });
    } catch (err) {
      list.innerHTML = UI.emptyState('Failed to load', err.message);
    }
  }

  return { render };
})());
