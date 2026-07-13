// ============================================================
// App shell — sidebar, theme, group switcher, hash router
// ============================================================

const App = (() => {
  const views = {};
  const breadcrumbs = {
    dashboard: ['Overview', 'Dashboard'],
    analytics: ['Overview', 'Analytics'],
    members: ['Overview', 'Members'],
    purgatory: ['Moderation', 'Purgatory'],
    flags: ['Moderation', 'Flagged Queue'],
    appeals: ['Moderation', 'Appeals'],
    modlog: ['Moderation', 'Mod Log'],
    audit: ['Moderation', 'Audit Trail'],
    ai: ['Automation', 'AI Configuration'],
    automation: ['Automation', 'Rules & Triggers'],
    scheduled: ['Automation', 'Scheduled Posts'],
    filters: ['Automation', 'Filters'],
    settings: ['System', 'Settings'],
    health: ['System', 'System Health'],
  };

  function register(name, view) {
    views[name] = view;
  }

  function setActiveNav(route) {
    document.querySelectorAll('.nav-item').forEach((el) => {
      el.classList.toggle('active', el.dataset.route === route);
    });
    const bc = breadcrumbs[route] || ['', route];
    document.getElementById('breadcrumb').innerHTML =
      `<span style="color:var(--text-muted);font-weight:400;">${UI.escapeHTML(bc[0])}</span> <span style="margin:0 6px;color:var(--text-dim);">/</span> ${UI.escapeHTML(bc[1])}`;
  }

  async function renderView(route) {
    const container = document.getElementById('view-container');
    if (!route || !views[route]) {
      container.innerHTML = UI.emptyState('Page not found', `Unknown view: ${route}`);
      return;
    }
    if (!API.getGroup()) {
      container.innerHTML = `<div class="empty-state">
        <svg viewBox="0 0 24 24" width="48" height="48"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5z" fill="currentColor"/></svg>
        <h3>Select a group</h3>
        <p>Pick a group from the sidebar switcher to start managing it.</p>
      </div>`;
      return;
    }
    setActiveNav(route);
    container.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Loading…</p></div>`;
    try {
      await views[route].render(container);
    } catch (err) {
      container.innerHTML = `<div class="empty-state">
        <h3 style="color:var(--danger);">Failed to load</h3>
        <p>${UI.escapeHTML(err.message || String(err))}</p>
      </div>`;
    }
  }

  function router() {
    const hash = window.location.hash.replace(/^#\/?/, '');
    const [route] = hash.split('?');
    renderView(route || 'dashboard');
  }

  // ---------- group switcher ----------
  let groups = [];
  async function loadGroups() {
    try {
      const data = await API.listGroups();
      groups = data.groups || [];
      renderGroupList(groups);
      if (groups.length > 0) {
        selectGroup(groups[0]);
      } else {
        document.getElementById('group-title').textContent = 'No groups';
        document.getElementById('group-subtitle').textContent = 'Add the bot to a group';
      }
    } catch (err) {
      UI.toast('Failed to load groups: ' + err.message, 'error');
    }
  }

  function renderGroupList(list) {
    const listEl = document.getElementById('group-list');
    if (list.length === 0) {
      listEl.innerHTML = `<div style="padding:14px;text-align:center;color:var(--text-muted);font-size:13px;">No groups found.<br>Add the bot to a Telegram group and run an admin command to register.</div>`;
      return;
    }
    listEl.innerHTML = list.map((g) => `
      <button data-id="${g.id}">
        <span class="group-avatar">${UI.escapeHTML(UI.initials(g.title))}</span>
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${UI.escapeHTML(g.title)}</span>
      </button>
    `).join('');
    listEl.querySelectorAll('button').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = parseInt(btn.dataset.id, 10);
        const g = groups.find((x) => x.id === id);
        if (g) selectGroup(g);
        document.getElementById('group-dropdown').hidden = true;
      });
    });
  }

  function selectGroup(g) {
    API.setGroup(g.id);
    document.getElementById('group-avatar').textContent = UI.initials(g.title);
    document.getElementById('group-title').textContent = g.title;
    document.getElementById('group-subtitle').textContent = `ID: ${g.id}`;
    // Connect WebSocket for real-time updates on this group
    if (typeof WS !== 'undefined') {
      WS.connect(g.id);
    }
    router();
    refreshBadges();
  }

  async function refreshBadges() {
    const gid = API.getGroup();
    if (!gid) return;
    try {
      const overview = await API.overview(gid);
      setBadge('badge-purgatory', overview.stats.pending_purgatory);
      setBadge('badge-flags', overview.stats.pending_flags);
      setBadge('badge-appeals', overview.stats.pending_appeals);
    } catch (e) { /* silent */ }
  }

  function setBadge(id, count) {
    const el = document.getElementById(id);
    if (!el) return;
    if (count > 0) {
      el.hidden = false;
      el.textContent = count > 99 ? '99+' : count;
    } else {
      el.hidden = true;
    }
  }

  // ---------- theme ----------
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('gb-theme', theme); } catch (e) {}
  }
  function initTheme() {
    let theme = 'dark';
    try { theme = localStorage.getItem('gb-theme') || 'dark'; } catch (e) {}
    applyTheme(theme);
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    applyTheme(current === 'dark' ? 'light' : 'dark');
  }

  // ---------- init ----------
  function init() {
    initTheme();
    document.getElementById('theme-toggle').addEventListener('click', toggleTheme);

    const sidebarToggle = document.getElementById('sidebar-toggle');
    sidebarToggle?.addEventListener('click', () => {
      document.querySelector('.app-grid').classList.toggle('sidebar-collapsed');
    });

    const mobileMenu = document.getElementById('mobile-menu');
    mobileMenu?.addEventListener('click', () => {
      document.getElementById('sidebar').classList.toggle('open');
    });

    const groupCurrent = document.getElementById('group-current');
    const groupDropdown = document.getElementById('group-dropdown');
    groupCurrent?.addEventListener('click', (e) => {
      e.stopPropagation();
      groupDropdown.hidden = !groupDropdown.hidden;
      if (!groupDropdown.hidden) document.getElementById('group-search')?.focus();
    });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#group-switcher')) groupDropdown.hidden = true;
    });
    const groupSearch = document.getElementById('group-search');
    groupSearch?.addEventListener('input', UI.debounce((e) => {
      const q = e.target.value.toLowerCase();
      renderGroupList(groups.filter((g) => g.title.toLowerCase().includes(q)));
    }, 150));

    document.getElementById('refresh-btn')?.addEventListener('click', () => {
      router();
      refreshBadges();
    });

    window.addEventListener('hashchange', router);
    loadGroups();

    // Auto-refresh badges every 60s
    setInterval(refreshBadges, 60000);
  }

  document.addEventListener('DOMContentLoaded', init);

  return { register, renderView, refreshBadges };
})();

window.App = App;
