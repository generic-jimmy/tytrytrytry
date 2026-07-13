// Post view — two-way dashboard chat (post to group from UI)
App.register('post', (() => {
  let templates = [];

  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>Post to Group</h1>
        <p>Send messages to the group directly from the dashboard — announcements, warnings, replies to flagged users.</p>
      </div>
      <div class="loading-state"><div class="spinner"></div><p>Loading…</p></div>
    `;
    try {
      const data = await API.request('GET', `/api/groups/${gid}/message-templates`);
      templates = data.templates || [];
    } catch (e) { /* templates optional */ }
    renderForm(container);
  }

  function renderForm(container) {
    container.innerHTML = `
      <div class="page-header">
        <h1>Post to Group</h1>
        <p>Send messages to the group directly from the dashboard — announcements, warnings, replies to flagged users.</p>
      </div>

      <div class="grid-2" style="grid-template-columns: 2fr 1fr;">
        <div class="section-block">
          <h3>Compose message</h3>
          <p class="section-desc">Supports HTML formatting. Messages are attributed to the bot on behalf of the dashboard admin (recorded in audit trail).</p>
          <div class="field">
            <label class="label">Message text</label>
            <textarea class="textarea" id="post-text" rows="6" placeholder="Type your message…"></textarea>
          </div>
          <div class="field">
            <label class="label">Reply to message ID (optional)</label>
            <input type="number" class="input" id="post-reply" placeholder="1234">
          </div>
          <div style="display:flex;gap:8px;align-items:center;">
            <button class="btn btn-lg" id="send-post">Send message</button>
            <span class="text-muted" style="font-size:12px;">Message will be posted immediately to the group.</span>
          </div>
        </div>

        <div class="section-block">
          <h3>Quick templates</h3>
          <p class="section-desc">Click to insert into the compose box.</p>
          <div style="display:flex;flex-direction:column;gap:8px;">
            ${templates.length === 0 ? '<p class="text-muted" style="font-size:12px;">No templates loaded.</p>' : templates.map((t) => `
              <button class="btn btn-ghost btn-sm" data-template="${UI.escapeAttr(t.text)}" style="text-align:left;white-space:normal;">${UI.escapeHTML(t.title)}</button>
            `).join('')}
          </div>
        </div>
      </div>
    `;

    document.getElementById('send-post').addEventListener('click', sendPost);
    container.querySelectorAll('button[data-template]').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.getElementById('post-text').value = btn.dataset.template;
        document.getElementById('post-text').focus();
      });
    });
  }

  async function sendPost() {
    const gid = API.getGroup();
    const text = document.getElementById('post-text').value.trim();
    const reply = document.getElementById('post-reply').value;
    if (!text) { UI.toast('Message text is required', 'info'); return; }
    const btn = document.getElementById('send-post');
    btn.disabled = true;
    btn.textContent = 'Sending…';
    try {
      const payload = { text };
      if (reply) payload.reply_to_message_id = parseInt(reply, 10);
      const res = await API.request('POST', `/api/groups/${gid}/post`, payload);
      UI.toast(`✓ Message sent (ID: ${res.message_id})`, 'success');
      document.getElementById('post-text').value = '';
      document.getElementById('post-reply').value = '';
    } catch (err) {
      UI.toast(`Failed: ${err.message}`, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Send message';
    }
  }

  return { render };
})());
