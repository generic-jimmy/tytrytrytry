// Scheduled messages view
App.register('scheduled', (() => {
  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>Scheduled Posts</h1>
        <p>Queue messages to be sent automatically. Set a repeat hour for daily posts.</p>
      </div>

      <div class="section-block">
        <h3>Schedule new message</h3>
        <p class="section-desc">Times are UTC. The bot checks every 30 seconds for due messages.</p>
        <div class="field">
          <label class="label">Message text</label>
          <textarea class="textarea" id="sched-text" placeholder="Daily reminder: read the rules at /rules"></textarea>
        </div>
        <div class="field-row">
          <div class="field">
            <label class="label">Scheduled for (UTC)</label>
            <input type="datetime-local" class="input" id="sched-time">
          </div>
          <div class="field">
            <label class="label">Repeat daily at hour (optional, 0-23)</label>
            <input type="number" class="input" id="sched-repeat" min="0" max="23" placeholder="no repeat">
          </div>
        </div>
        <button class="btn" id="add-sched">Schedule message</button>
      </div>

      <div class="section-block">
        <h3>Scheduled messages</h3>
        <div id="sched-list"><div class="loading-state"><div class="spinner"></div><p>Loading…</p></div></div>
      </div>
    `;

    document.getElementById('add-sched').addEventListener('click', async () => {
      const text = document.getElementById('sched-text').value.trim();
      const timeVal = document.getElementById('sched-time').value;
      const repeatRaw = document.getElementById('sched-repeat').value;
      if (!text || !timeVal) { UI.toast('Text and time are required', 'info'); return; }
      // datetime-local returns local time; convert to ISO UTC
      const local = new Date(timeVal);
      const iso = local.toISOString();
      const repeat_hour = repeatRaw === '' ? null : parseInt(repeatRaw, 10);
      try {
        await API.addScheduled(gid, { text, scheduled_for: iso, repeat_hour });
        UI.toast('Message scheduled', 'success');
        document.getElementById('sched-text').value = '';
        document.getElementById('sched-time').value = '';
        document.getElementById('sched-repeat').value = '';
        loadList();
      } catch (err) {
        UI.toast(`Failed: ${err.message}`, 'error');
      }
    });

    await loadList();
  }

  async function loadList() {
    const gid = API.getGroup();
    const list = document.getElementById('sched-list');
    if (!list) return;
    list.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Loading…</p></div>`;
    try {
      const data = await API.listScheduled(gid);
      if (data.scheduled.length === 0) {
        list.innerHTML = UI.emptyState('No scheduled messages', 'Schedule one above.');
        return;
      }
      list.innerHTML = data.scheduled.map((s) => `
        <div class="timeline-item">
          <div class="ti-time">
            <div>${UI.formatDateTime(s.scheduled_for)}</div>
            ${s.repeat_hour !== null && s.repeat_hour !== undefined ? `<div class="badge badge-info" style="margin-top:4px;">repeats daily @ ${s.repeat_hour}:00</div>` : ''}
            ${s.sent ? `<div class="badge badge-success" style="margin-top:4px;">sent</div>` : ''}
          </div>
          <div class="ti-body">
            <strong>${UI.escapeHTML(s.text.slice(0, 100))}${s.text.length > 100 ? '…' : ''}</strong>
            <small>Scheduled by admin ${s.created_by || '?'}</small>
            ${!s.sent ? `<div style="margin-top:6px;"><button class="btn btn-danger btn-sm" data-del="${s.id}">Cancel</button></div>` : ''}
          </div>
        </div>
      `).join('');

      list.querySelectorAll('button[data-del]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const id = parseInt(btn.dataset.del, 10);
          UI.confirmModal({
            title: 'Cancel scheduled message?',
            message: 'This will remove the message from the queue.',
            confirmText: 'Cancel message',
            danger: true,
            onConfirm: async () => {
              try {
                await API.deleteScheduled(gid, id);
                UI.toast('Cancelled', 'success');
                loadList();
              } catch (err) {
                UI.toast(`Failed: ${err.message}`, 'error');
              }
            },
          });
        });
      });
    } catch (err) {
      list.innerHTML = UI.emptyState('Failed to load', err.message);
    }
  }

  return { render };
})());
