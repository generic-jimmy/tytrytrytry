// Settings view — comprehensive multi-section form
App.register('settings', (() => {
  let group = null;

  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>Settings</h1>
        <p>Group configuration, moderation policies, night mode, and dashboard preferences.</p>
      </div>
      <div class="loading-state"><div class="spinner"></div><p>Loading settings…</p></div>
    `;
    try {
      group = await API.getSettings(gid);
    } catch (err) {
      container.innerHTML = UI.emptyState('Failed to load', err.message);
      return;
    }

    container.innerHTML = `
      <div class="page-header">
        <h1>Settings</h1>
        <p>Group configuration, moderation policies, night mode, and dashboard preferences.</p>
      </div>

      <div class="section-block">
        <h3>General</h3>
        <p class="section-desc">Basic group identity and onboarding messages.</p>
        <div class="field">
          <label class="label">Group title</label>
          <input class="input" id="set-title" value="${UI.escapeAttr(group.title)}">
        </div>
        <div class="field">
          <label class="label">Welcome message</label>
          <textarea class="textarea" id="set-welcome" rows="3">${UI.escapeHTML(group.welcome_message)}</textarea>
        </div>
        <div class="field">
          <label class="label">Rules <span class="hint-inline">shown when users type /brules</span></label>
          <textarea class="textarea" id="set-rules" rows="5">${UI.escapeHTML(group.rules)}</textarea>
        </div>
      </div>

      <div class="section-block">
        <h3>Moderation</h3>
        <p class="section-desc">Controls for the always-on moderation layer.</p>
        <div class="field-row" style="margin-bottom:14px;">
          <label class="toggle" style="margin-right:10px;">
            <input type="checkbox" id="set-ai-mod" ${group.ai_moderation_enabled ? 'checked' : ''}>
            <span class="toggle-slider"></span>
          </label>
          <div>
            <strong style="font-size:13px;display:block;">AI moderation</strong>
            <small class="text-muted" style="font-size:11px;">Run every message through the AI classifier.</small>
          </div>
        </div>
        <div class="field-row" style="margin-bottom:14px;">
          <label class="toggle" style="margin-right:10px;">
            <input type="checkbox" id="set-purgatory" ${group.purgatory_enabled ? 'checked' : ''}>
            <span class="toggle-slider"></span>
          </label>
          <div>
            <strong style="font-size:13px;display:block;">Purgatory</strong>
            <small class="text-muted" style="font-size:11px;">Hold new members for admin approval before they can post.</small>
          </div>
        </div>
        <div class="field-row">
          <div class="field">
            <label class="label">Warn limit <span class="hint-inline">auto-mute after this many</span></label>
            <input type="number" class="input" id="set-warn-limit" min="1" value="${group.warn_limit}">
          </div>
          <div class="field">
            <label class="label">Slow mode (seconds, 0 = off)</label>
            <input type="number" class="input" id="set-slow-mode" min="0" value="${group.slow_mode_seconds}">
          </div>
        </div>
      </div>

      <div class="section-block">
        <h3>Night mode</h3>
        <p class="section-desc">Delete non-admin messages during set UTC hours.</p>
        <div class="field-row" style="margin-bottom:14px;">
          <label class="toggle" style="margin-right:10px;">
            <input type="checkbox" id="set-night" ${group.night_mode_enabled ? 'checked' : ''}>
            <span class="toggle-slider"></span>
          </label>
          <strong style="font-size:13px;">Enable night mode</strong>
        </div>
        <div class="field-row">
          <div class="field">
            <label class="label">Start hour (UTC, 0-23)</label>
            <input type="number" class="input" id="set-night-start" min="0" max="23" value="${group.night_start_hour}">
          </div>
          <div class="field">
            <label class="label">End hour (UTC, 0-23)</label>
            <input type="number" class="input" id="set-night-end" min="0" max="23" value="${group.night_end_hour}">
          </div>
        </div>
      </div>

      <div class="section-block">
        <h3>Mod log channel</h3>
        <p class="section-desc">Mirror every moderation action to a Telegram channel. The bot must already be an admin in that channel.</p>
        <div class="field">
          <label class="label">Channel ID</label>
          <input type="number" class="input" id="set-log-channel" placeholder="-1001234567890" value="${group.mod_log_channel_id || ''}">
        </div>
      </div>

      <div class="section-block">
        <h3>Dashboard</h3>
        <p class="section-desc">Cosmetic preferences for this group's dashboard view.</p>
        <div class="field">
          <label class="label">Theme preference (visual hint only)</label>
          <select class="select" id="set-theme" style="width:auto;">
            <option value="dark" ${group.dashboard_theme === 'dark' ? 'selected' : ''}>Dark</option>
            <option value="light" ${group.dashboard_theme === 'light' ? 'selected' : ''}>Light</option>
          </select>
        </div>
      </div>

      <div style="display:flex;gap:8px;align-items:center;">
        <button class="btn btn-lg" id="save-settings">Save all settings</button>
        <span class="text-muted" style="font-size:12px;">Last saved: just now</span>
      </div>
    `;

    document.getElementById('save-settings').addEventListener('click', saveAll);
  }

  async function saveAll() {
    const gid = API.getGroup();
    const payload = {
      welcome_message: document.getElementById('set-welcome').value,
      rules: document.getElementById('set-rules').value,
      ai_moderation_enabled: document.getElementById('set-ai-mod').checked,
      purgatory_enabled: document.getElementById('set-purgatory').checked,
      night_mode_enabled: document.getElementById('set-night').checked,
      night_start_hour: parseInt(document.getElementById('set-night-start').value, 10),
      night_end_hour: parseInt(document.getElementById('set-night-end').value, 10),
      warn_limit: parseInt(document.getElementById('set-warn-limit').value, 10),
      slow_mode_seconds: parseInt(document.getElementById('set-slow-mode').value, 10),
      mod_log_channel_id: document.getElementById('set-log-channel').value || null,
      dashboard_theme: document.getElementById('set-theme').value,
    };
    try {
      await API.updateSettings(gid, payload);
      UI.toast('Settings saved', 'success');
    } catch (err) {
      UI.toast(`Failed: ${err.message}`, 'error');
    }
  }

  return { render };
})());
