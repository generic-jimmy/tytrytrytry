// ============================================================
// UI helpers — toast, modal, drawer, formatting, escape
// ============================================================

const UI = (() => {

  // ---------- escape ----------
  function escapeHTML(s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function escapeAttr(s) { return escapeHTML(s); }

  // ---------- formatting ----------
  function timeAgo(iso) {
    if (!iso) return '—';
    const dt = new Date(iso);
    const diff = (Date.now() - dt.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
    return dt.toLocaleDateString();
  }

  function formatDateTime(iso) {
    if (!iso) return '—';
    const dt = new Date(iso);
    return dt.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
  }

  function formatNumber(n) {
    if (n === null || n === undefined) return '0';
    return new Intl.NumberFormat().format(n);
  }

  function initials(name) {
    if (!name) return '?';
    const parts = String(name).trim().split(/\s+/);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  // ---------- toast ----------
  function toast(message, kind = 'info', duration = 3500) {
    const stack = document.getElementById('toast-stack');
    if (!stack) return;
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.textContent = message;
    stack.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(8px)';
      el.style.transition = 'all 250ms';
      setTimeout(() => el.remove(), 250);
    }, duration);
  }

  // ---------- modal ----------
  function modal({ title, body, footer, size }) {
    const root = document.getElementById('modal-root');
    if (!root) return () => {};
    root.hidden = false;
    root.innerHTML = '';

    const backdrop = document.createElement('div');
    backdrop.className = 'modal-root';
    backdrop.style.position = 'fixed';
    backdrop.style.inset = '0';
    backdrop.style.zIndex = '999';
    backdrop.style.background = 'rgba(0,0,0,0.6)';
    backdrop.style.backdropFilter = 'blur(6px)';
    backdrop.style.display = 'flex';
    backdrop.style.alignItems = 'center';
    backdrop.style.justifyContent = 'center';
    backdrop.style.padding = '20px';

    const m = document.createElement('div');
    m.className = 'modal';
    if (size === 'lg') { m.style.maxWidth = '780px'; }
    m.innerHTML = `
      <div class="modal-head">
        <div><h3>${escapeHTML(title || '')}</h3></div>
        <button class="modal-close" aria-label="Close">
          <svg viewBox="0 0 24 24" width="18" height="18"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" fill="currentColor"/></svg>
        </button>
      </div>
      <div class="modal-body"></div>
      ${footer ? `<div class="modal-foot"></div>` : ''}
    `;

    const bodyEl = m.querySelector('.modal-body');
    if (typeof body === 'string') bodyEl.innerHTML = body;
    else if (body instanceof Node) bodyEl.appendChild(body);

    if (footer) {
      const footEl = m.querySelector('.modal-foot');
      if (typeof footer === 'string') footEl.innerHTML = footer;
      else if (footer instanceof Node) footEl.appendChild(footer);
    }

    backdrop.appendChild(m);
    root.appendChild(backdrop);

    const close = () => {
      backdrop.style.opacity = '0';
      backdrop.style.transition = 'opacity 180ms';
      setTimeout(() => {
        root.innerHTML = '';
        root.hidden = true;
      }, 180);
    };

    m.querySelector('.modal-close').addEventListener('click', close);
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close(); });
    document.addEventListener('keydown', function esc(e) {
      if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); }
    });

    return { close, el: m };
  }

  function confirmModal({ title, message, confirmText = 'Confirm', danger = false, onConfirm }) {
    const footer = document.createElement('div');
    const btnCancel = document.createElement('button');
    btnCancel.className = 'btn btn-ghost';
    btnCancel.textContent = 'Cancel';
    const btnConfirm = document.createElement('button');
    btnConfirm.className = danger ? 'btn btn-danger' : 'btn';
    btnConfirm.textContent = confirmText;
    footer.appendChild(btnCancel);
    footer.appendChild(btnConfirm);

    const m = modal({
      title,
      body: `<p style="color:var(--text-muted);margin:0;font-size:13px;line-height:1.6;">${escapeHTML(message)}</p>`,
      footer,
    });

    btnCancel.addEventListener('click', m.close);
    btnConfirm.addEventListener('click', () => {
      m.close();
      if (onConfirm) onConfirm();
    });
  }

  // ---------- drawer ----------
  function drawer({ title, body, footer }) {
    const root = document.getElementById('modal-root');
    if (!root) return () => {};
    root.hidden = false;
    root.innerHTML = '';

    const backdrop = document.createElement('div');
    backdrop.style.position = 'fixed';
    backdrop.style.inset = '0';
    backdrop.style.background = 'rgba(0,0,0,0.4)';
    backdrop.style.zIndex = '997';

    const d = document.createElement('div');
    d.className = 'drawer';
    d.innerHTML = `
      <div class="drawer-head">
        <h3 style="margin:0;font-size:15px;">${escapeHTML(title || '')}</h3>
        <button class="modal-close" aria-label="Close">
          <svg viewBox="0 0 24 24" width="18" height="18"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" fill="currentColor"/></svg>
        </button>
      </div>
      <div class="drawer-body"></div>
      ${footer ? `<div class="drawer-foot"></div>` : ''}
    `;

    const bodyEl = d.querySelector('.drawer-body');
    if (typeof body === 'string') bodyEl.innerHTML = body;
    else if (body instanceof Node) bodyEl.appendChild(body);

    if (footer) {
      const footEl = d.querySelector('.drawer-foot');
      if (typeof footer === 'string') footEl.innerHTML = footer;
      else if (footer instanceof Node) footEl.appendChild(footer);
    }

    root.appendChild(backdrop);
    root.appendChild(d);

    const close = () => {
      d.style.transform = 'translateX(100%)';
      d.style.transition = 'transform 220ms';
      backdrop.style.opacity = '0';
      backdrop.style.transition = 'opacity 220ms';
      setTimeout(() => {
        root.innerHTML = '';
        root.hidden = true;
      }, 220);
    };

    d.querySelector('.modal-close').addEventListener('click', close);
    backdrop.addEventListener('click', close);

    return { close, el: d };
  }

  // ---------- loading skeleton ----------
  function skeleton(rows = 4) {
    return Array.from({ length: rows }).map(() =>
      `<div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;height:64px;margin-bottom:8px;position:relative;overflow:hidden;">
        <div style="position:absolute;inset:0;background:linear-gradient(90deg,transparent,var(--surface-hover),transparent);animation:shimmer 1.5s infinite;"></div>
      </div>`
    ).join('');
  }

  // ---------- empty state ----------
  function emptyState(title, message, icon = null) {
    return `
      <div class="empty-state">
        ${icon || '<svg viewBox="0 0 24 24" width="48" height="48"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 14H7v-2h5v2zm5-4H7v-2h10v2zm0-4H7V7h10v2z" fill="currentColor"/></svg>'}
        <h3>${escapeHTML(title)}</h3>
        <p>${escapeHTML(message)}</p>
      </div>
    `;
  }

  // ---------- debounce ----------
  function debounce(fn, delay = 300) {
    let t;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  // ---------- form serializer ----------
  function serializeForm(form) {
    const out = {};
    const fd = new FormData(form);
    for (const [k, v] of fd.entries()) {
      if (out[k] !== undefined) {
        if (!Array.isArray(out[k])) out[k] = [out[k]];
        out[k].push(v);
      } else {
        out[k] = v;
      }
    }
    return out;
  }

  return {
    escapeHTML, escapeAttr,
    timeAgo, formatDateTime, formatNumber, initials,
    toast, modal, confirmModal, drawer,
    skeleton, emptyState, debounce, serializeForm,
  };
})();

// shimmer animation
const styleShimmer = document.createElement('style');
styleShimmer.textContent = `@keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }`;
document.head.appendChild(styleShimmer);
