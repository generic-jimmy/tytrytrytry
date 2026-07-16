// AI Configuration view — model picker, prompts, thresholds, playground
App.register('ai', (() => {
  let cfg = null;

  async function render(container) {
    const gid = API.getGroup();
    container.innerHTML = `
      <div class="page-header">
        <h1>AI Configuration</h1>
        <p>Tune the moderation model, thresholds, prompts, and test changes live before deploying.</p>
      </div>
      <div class="loading-state"><div class="spinner"></div><p>Loading AI config…</p></div>
    `;
    try {
      cfg = await API.getAIConfig(gid);
    } catch (err) {
      container.innerHTML = UI.emptyState('Failed to load', err.message);
      return;
    }

    const cats = (cfg.enabled_categories || '').split(',').filter(Boolean);
    const allCats = ['spam', 'toxicity', 'threat', 'scam_link', 'other'];

    container.innerHTML = `
      <div class="page-header">
        <h1>AI Configuration</h1>
        <p>Tune the moderation model, thresholds, prompts, and test changes live before deploying.</p>
      </div>

      <div class="ai-grid">
        <div class="ai-panel">
          <h3>Model & Behavior</h3>

          <div class="field">
            <label class="label">Model <span class="hint-inline">type or pick — polls ALL free models as fallback</span></label>
            <input class="input" id="ai-model" list="ai-model-list" value="${UI.escapeAttr(cfg.model)}" placeholder="e.g. meta-llama/llama-3.3-70b-instruct:free" autocomplete="off" spellcheck="false" style="font-family:var(--font-mono);font-size:12px;">
            <datalist id="ai-model-list">
              ${cfg.available_models.map((m) => `<option value="${m.value}">${UI.escapeHTML(m.label)}</option>`).join('')}
            </datalist>
            <small class="text-muted" style="font-size:11px;display:block;margin-top:4px;">
              Pick from the dropdown or type any OpenRouter model ID (e.g. <code>anthropic/claude-3.5-sonnet</code> for paid models).
              Use <code>__all_free__</code> to poll through every free model until one works. Falls back through the full free list automatically on any failure.
            </small>
          </div>

          <div class="field">
            <label class="label">Temperature <span class="hint-inline">creativity vs determinism</span></label>
            <div class="slider-row">
              <input type="range" id="ai-temp" min="0" max="2" step="0.05" value="${cfg.temperature}">
              <span class="slider-value mono" id="ai-temp-val">${cfg.temperature.toFixed(2)}</span>
            </div>
          </div>

          <div class="field">
            <label class="label">Confidence threshold <span class="hint-inline">minimum to act on high-severity</span></label>
            <div class="slider-row">
              <input type="range" id="ai-conf" min="0" max="1" step="0.05" value="${cfg.confidence_threshold}">
              <span class="slider-value mono" id="ai-conf-val">${(cfg.confidence_threshold * 100).toFixed(0)}%</span>
            </div>
          </div>

          <div class="field">
            <label class="label">Enabled categories</label>
            <div class="category-grid" id="cat-grid">
              ${allCats.map((c) => `
                <div class="category-chip ${cats.includes(c) ? 'active' : ''}" data-cat="${c}">${UI.escapeHTML(c)}</div>
              `).join('')}
            </div>
          </div>

          <div class="field-row" style="margin-bottom:16px;">
            <label class="toggle" style="margin-right:10px;">
              <input type="checkbox" id="ai-auto-ban" ${cfg.auto_ban_high ? 'checked' : ''}>
              <span class="toggle-slider"></span>
            </label>
            <div>
              <strong style="font-size:13px;display:block;">Auto-ban high-severity</strong>
              <small class="text-muted" style="font-size:11px;">Automatically delete + ban on high-severity flags above the confidence threshold.</small>
            </div>
          </div>

          <div class="field-row" style="margin-bottom:20px;">
            <label class="toggle" style="margin-right:10px;">
              <input type="checkbox" id="ai-auto-flag" ${cfg.auto_flag_medium ? 'checked' : ''}>
              <span class="toggle-slider"></span>
            </label>
            <div>
              <strong style="font-size:13px;display:block;">Auto-flag medium/low</strong>
              <small class="text-muted" style="font-size:11px;">Queue medium/low severity messages for human review.</small>
            </div>
          </div>

          <button class="btn btn-lg" id="save-ai-config">Save configuration</button>
        </div>

        <div class="ai-panel">
          <h3>System Prompt</h3>
          <p style="font-size:12px;color:var(--text-muted);margin:0 0 10px;">Customize the moderation system prompt. Leave empty to use the default.</p>
          <textarea class="prompt-editor" id="ai-prompt" placeholder="Leave empty to use default prompt…">${UI.escapeHTML(cfg.custom_system_prompt)}</textarea>
          <button class="btn btn-ghost btn-sm" id="reset-prompt" style="margin-top:8px;">Reset to default</button>

          <h3 style="margin-top:24px;">Test Playground</h3>
          <p style="font-size:12px;color:var(--text-muted);margin:0 0 10px;">Send a test message to see how the AI would classify it with the current config.</p>
          <textarea class="textarea" id="test-input" placeholder="Type a test message…" style="min-height:60px;margin-bottom:8px;"></textarea>
          <div style="display:flex;gap:8px;margin-bottom:10px;">
            <button class="btn btn-sm" id="test-classify">Classify (moderation)</button>
            <button class="btn btn-ghost btn-sm" id="test-raw">Raw call</button>
          </div>
          <div class="playground-output" id="test-output">Output will appear here…</div>
        </div>
      </div>
    `;

    // Wire events
    const tempEl = document.getElementById('ai-temp');
    const tempVal = document.getElementById('ai-temp-val');
    tempEl.addEventListener('input', () => { tempVal.textContent = parseFloat(tempEl.value).toFixed(2); });

    const confEl = document.getElementById('ai-conf');
    const confVal = document.getElementById('ai-conf-val');
    confEl.addEventListener('input', () => { confVal.textContent = (parseFloat(confEl.value) * 100).toFixed(0) + '%'; });

    container.querySelectorAll('.category-chip').forEach((chip) => {
      chip.addEventListener('click', () => chip.classList.toggle('active'));
    });

    document.getElementById('reset-prompt').addEventListener('click', () => {
      document.getElementById('ai-prompt').value = '';
    });

    document.getElementById('save-ai-config').addEventListener('click', saveConfig);

    document.getElementById('test-classify').addEventListener('click', () => runTest('classify'));
    document.getElementById('test-raw').addEventListener('click', () => runTest('raw'));
  }

  async function saveConfig() {
    const gid = API.getGroup();
    const activeCats = Array.from(document.querySelectorAll('.category-chip.active')).map((c) => c.dataset.cat);
    const payload = {
      model: document.getElementById('ai-model').value,
      temperature: parseFloat(document.getElementById('ai-temp').value),
      confidence_threshold: parseFloat(document.getElementById('ai-conf').value),
      custom_system_prompt: document.getElementById('ai-prompt').value,
      auto_ban_high: document.getElementById('ai-auto-ban').checked,
      auto_flag_medium: document.getElementById('ai-auto-flag').checked,
      enabled_categories: activeCats.join(','),
    };
    try {
      await API.updateAIConfig(gid, payload);
      UI.toast('AI configuration saved', 'success');
    } catch (err) {
      UI.toast(`Failed: ${err.message}`, 'error');
    }
  }

  async function runTest(mode) {
    const gid = API.getGroup();
    const input = document.getElementById('test-input').value.trim();
    const out = document.getElementById('test-output');
    if (!input) { UI.toast('Enter a test message first', 'info'); return; }

    out.innerHTML = `<div class="spinner" style="width:20px;height:20px;border-width:2px;"></div> <span style="margin-left:8px;color:var(--text-muted);font-size:12px;">Calling model…</span>`;

    const systemPrompt = document.getElementById('ai-prompt').value.trim();
    const fullSystem = mode === 'classify'
      ? (systemPrompt || `You moderate messages in a Telegram group chat. Respond with ONLY a JSON object: {"category": "none|spam|toxicity|threat|scam_link|other", "severity": "none|low|medium|high", "confidence": 0.0-1.0}`)
      : (systemPrompt || 'You are a helpful Telegram group admin assistant.');

    try {
      const data = await API.testAIPrompt(gid, { user_prompt: input, system_prompt: fullSystem });
      out.textContent = data.response;
      if (mode === 'classify') {
        try {
          const parsed = JSON.parse(data.response);
          out.innerHTML = `<div style="margin-bottom:8px;">
            <span class="badge badge-${parsed.severity === 'high' ? 'danger' : parsed.severity === 'medium' ? 'warn' : 'info'}">${UI.escapeHTML(parsed.category || 'none')}</span>
            <span class="badge">${UI.escapeHTML(parsed.severity || 'none')}</span>
            <span class="mono" style="font-size:11px;color:var(--text-muted);">confidence: ${((parsed.confidence || 0) * 100).toFixed(0)}%</span>
          </div>
          <pre style="margin:0;font-family:inherit;white-space:pre-wrap;">${UI.escapeHTML(data.response)}</pre>`;
        } catch (e) {
          out.textContent = data.response;
        }
      }
    } catch (err) {
      out.innerHTML = `<span class="text-danger">Error: ${UI.escapeHTML(err.message)}</span>`;
    }
  }

  return { render };
})());
