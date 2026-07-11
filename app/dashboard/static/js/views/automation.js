// Automation view — custom commands + auto-responses
App.register('automation', (() => {
  let activeTab = 'commands';

  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>Rules &amp; Triggers</h1>
        <p>Build custom commands and auto-responses. Changes apply immediately.</p>
      </div>
      <div class="tabs">
        <button class="tab ${activeTab === 'commands' ? 'active' : ''}" data-tab="commands">Custom Commands</button>
        <button class="tab ${activeTab === 'responses' ? 'active' : ''}" data-tab="responses">Auto-Responses</button>
      </div>
      <div id="automation-body"><div class="loading-state"><div class="spinner"></div><p>Loading…</p></div></div>
    `;

    container.querySelectorAll('.tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        activeTab = tab.dataset.tab;
        container.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');
        loadTab();
      });
    });

    await loadTab();
  }

  async function loadTab() {
    const gid = API.getGroup();
    const body = document.getElementById('automation-body');
    if (!body) return;
    body.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Loading…</p></div>`;

    if (activeTab === 'commands') {
      await loadCommands(body, gid);
    } else {
      await loadResponses(body, gid);
    }
  }

  async function loadCommands(body, gid) {
    try {
      const data = await API.listCustomCommands(gid);
      body.innerHTML = `
        <div class="section-block">
          <h3>Create custom command</h3>
          <p class="section-desc">Users in the group can type <code class="mono">/&lt;trigger&gt;</code> to get the response. Trigger must be one word, no leading slash.</p>
          <div class="field-row">
            <div class="field" style="max-width:200px;">
              <label class="label">Trigger</label>
              <input class="input" id="cmd-trigger" placeholder="discord">
            </div>
            <div class="field" style="flex:1;">
              <label class="label">Response</label>
              <input class="input" id="cmd-response" placeholder="Join us at https://discord.gg/...">
            </div>
          </div>
          <button class="btn" id="add-cmd">Add command</button>
        </div>

        <div class="section-block">
          <h3>Existing commands (${data.commands.length})</h3>
          ${data.commands.length === 0 ? UI.emptyState('No custom commands yet', 'Add one above to get started.') : `
            ${data.commands.map((c) => `
              <div class="rule-row">
                <span class="rule-trigger">/${UI.escapeHTML(c.trigger)}</span>
                <span class="rule-arrow">→</span>
                <span class="rule-response">${UI.escapeHTML(c.response)}</span>
                <div class="rule-actions">
                  <button class="btn btn-ghost btn-sm" data-copy="${c.id}">Copy</button>
                  <button class="btn btn-danger btn-sm" data-del="${c.id}">Delete</button>
                </div>
              </div>
            `).join('')}
          `}
        </div>
      `;

      document.getElementById('add-cmd').addEventListener('click', async () => {
        const trigger = document.getElementById('cmd-trigger').value.trim().replace(/^\//, '').toLowerCase();
        const response = document.getElementById('cmd-response').value.trim();
        if (!trigger || !response) { UI.toast('Both trigger and response are required', 'info'); return; }
        try {
          await API.addCustomCommand(gid, { trigger, response });
          UI.toast('Command added', 'success');
          loadTab();
        } catch (err) {
          UI.toast(`Failed: ${err.message}`, 'error');
        }
      });

      body.querySelectorAll('button[data-del]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const id = parseInt(btn.dataset.del, 10);
          UI.confirmModal({
            title: 'Delete command?',
            message: 'This cannot be undone.',
            confirmText: 'Delete',
            danger: true,
            onConfirm: async () => {
              try {
                await API.deleteCustomCommand(gid, id);
                UI.toast('Command deleted', 'success');
                loadTab();
              } catch (err) {
                UI.toast(`Failed: ${err.message}`, 'error');
              }
            },
          });
        });
      });

      body.querySelectorAll('button[data-copy]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const row = btn.closest('.rule-row');
          const trigger = row.querySelector('.rule-trigger').textContent.slice(1);
          const response = row.querySelector('.rule-response').textContent;
          document.getElementById('cmd-trigger').value = trigger;
          document.getElementById('cmd-response').value = response;
        });
      });
    } catch (err) {
      body.innerHTML = UI.emptyState('Failed to load', err.message);
    }
  }

  async function loadResponses(body, gid) {
    try {
      const data = await API.listAutoResponses(gid);
      body.innerHTML = `
        <div class="section-block">
          <h3>Create auto-response</h3>
          <p class="section-desc">When a user's message matches the trigger, the bot replies with the response. Filters still apply separately.</p>
          <div class="field-row">
            <div class="field" style="flex:1;">
              <label class="label">Trigger phrase</label>
              <input class="input" id="ar-trigger" placeholder="how do I join">
            </div>
            <div class="field" style="flex:1;">
              <label class="label">Response</label>
              <input class="input" id="ar-response" placeholder="Type /rules to see the group rules">
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label class="label">Match type</label>
              <select class="select" id="ar-match">
                <option value="contains">Contains (substring)</option>
                <option value="exact">Exact match</option>
                <option value="regex">Regex pattern</option>
              </select>
            </div>
            <div class="field">
              <label class="label">Case sensitive?</label>
              <label class="toggle" style="margin-top:6px;">
                <input type="checkbox" id="ar-case">
                <span class="toggle-slider"></span>
              </label>
            </div>
          </div>
          <button class="btn" id="add-ar">Add auto-response</button>
        </div>

        <div class="section-block">
          <h3>Existing rules (${data.responses.length})</h3>
          ${data.responses.length === 0 ? UI.emptyState('No auto-responses yet', 'Add one above to get started.') : `
            ${data.responses.map((r) => `
              <div class="rule-row">
                <span class="rule-trigger">${UI.escapeHTML(r.trigger)}</span>
                <span class="badge">${UI.escapeHTML(r.match_type)}${r.case_sensitive ? ' · CS' : ''}</span>
                <span class="rule-arrow">→</span>
                <span class="rule-response">${UI.escapeHTML(r.response)}</span>
                <div class="rule-actions">
                  <label class="toggle" title="Enable/disable">
                    <input type="checkbox" data-toggle="${r.id}" ${r.enabled ? 'checked' : ''}>
                    <span class="toggle-slider"></span>
                  </label>
                  <button class="btn btn-danger btn-sm" data-del="${r.id}">Delete</button>
                </div>
              </div>
            `).join('')}
          `}
        </div>
      `;

      document.getElementById('add-ar').addEventListener('click', async () => {
        const trigger = document.getElementById('ar-trigger').value.trim();
        const response = document.getElementById('ar-response').value.trim();
        const match_type = document.getElementById('ar-match').value;
        const case_sensitive = document.getElementById('ar-case').checked;
        if (!trigger || !response) { UI.toast('Both trigger and response are required', 'info'); return; }
        try {
          await API.addAutoResponse(gid, { trigger, response, match_type, case_sensitive, enabled: true });
          UI.toast('Auto-response added', 'success');
          loadTab();
        } catch (err) {
          UI.toast(`Failed: ${err.message}`, 'error');
        }
      });

      body.querySelectorAll('input[data-toggle]').forEach((toggle) => {
        toggle.addEventListener('change', async () => {
          const id = parseInt(toggle.dataset.toggle, 10);
          try {
            await API.updateAutoResponse(gid, id, { enabled: toggle.checked });
            UI.toast(toggle.checked ? 'Enabled' : 'Disabled', 'success');
          } catch (err) {
            UI.toast(`Failed: ${err.message}`, 'error');
            toggle.checked = !toggle.checked;
          }
        });
      });

      body.querySelectorAll('button[data-del]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const id = parseInt(btn.dataset.del, 10);
          UI.confirmModal({
            title: 'Delete auto-response?',
            message: 'This cannot be undone.',
            confirmText: 'Delete',
            danger: true,
            onConfirm: async () => {
              try {
                await API.deleteAutoResponse(gid, id);
                UI.toast('Deleted', 'success');
                loadTab();
              } catch (err) {
                UI.toast(`Failed: ${err.message}`, 'error');
              }
            },
          });
        });
      });
    } catch (err) {
      body.innerHTML = UI.emptyState('Failed to load', err.message);
    }
  }

  return { render };
})());
