// ============================================================
// Real-time client — tries WebSocket, falls back to long-polling.
// Many hosting platforms (Render.com, corporate proxies) break the
// WebSocket Upgrade header. We detect that and transparently switch
// to polling /api/events every 2s — same event stream, just pulled
// instead of pushed.
// ============================================================

const WS = (() => {
  let socket = null;
  let reconnectAttempts = 0;
  let reconnectTimer = null;
  let pingTimer = null;
  let currentGroupId = null;
  let fallbackPolling = false;
  let pollTimer = null;
  let lastEventTime = 0;
  const listeners = new Map(); // event_type -> Set<callback>

  function connect(groupId) {
    if (currentGroupId === groupId && (socket || fallbackPolling)) return;
    currentGroupId = groupId;
    teardown();
    if (fallbackPolling) {
      startPolling();
    } else {
      tryConnect();
    }
  }

  function teardown() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (socket) {
      try { socket.close(); } catch (e) {}
      socket = null;
    }
  }

  function tryConnect() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/api/ws?group_id=${currentGroupId}`;
    try {
      socket = new WebSocket(url);
    } catch (e) {
      console.warn('[WS] construction failed, switching to polling', e);
      switchToPolling();
      return;
    }

    socket.onopen = () => {
      reconnectAttempts = 0;
      console.log('[WS] connected to group', currentGroupId);
      if (pingTimer) clearInterval(pingTimer);
      pingTimer = setInterval(() => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          try { socket.send('ping'); } catch (e) {}
        }
      }, 25000);
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'pong') return;
        if (data.type === 'error') {
          console.warn('[WS] server error:', data.payload);
          return;
        }
        handleEvent(data);
      } catch (e) {
        console.warn('[WS] failed to parse message:', e);
      }
    };

    socket.onerror = (e) => {
      console.warn('[WS] error', e);
    };

    socket.onclose = () => {
      console.log('[WS] disconnected');
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
      socket = null;
      // After 2 failed attempts, assume the platform doesn't support WS
      // (Render.com, some proxies) and switch to long-polling permanently.
      if (reconnectAttempts >= 1 && !fallbackPolling) {
        console.log('[WS] switching to long-polling fallback (WS unsupported by host)');
        switchToPolling();
        return;
      }
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectAttempts++;
    if (reconnectAttempts > 5) {
      console.warn('[WS] giving up after 5 attempts — switching to polling');
      switchToPolling();
      return;
    }
    const delay = Math.min(30000, 1000 * Math.pow(2, reconnectAttempts));
    console.log(`[WS] reconnecting in ${delay}ms (attempt ${reconnectAttempts})`);
    reconnectTimer = setTimeout(() => {
      if (currentGroupId) tryConnect();
    }, delay);
  }

  function switchToPolling() {
    fallbackPolling = true;
    teardown();
    startPolling();
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    console.log('[WS] polling /api/events every 2s for group', currentGroupId);
    // Initial fetch immediately
    pollOnce();
    pollTimer = setInterval(pollOnce, 2000);
  }

  async function pollOnce() {
    if (!currentGroupId) return;
    try {
      const res = await fetch(`/api/events?group_id=${currentGroupId}&since=${lastEventTime}`, {
        credentials: 'include',
      });
      if (!res.ok) return;
      const data = await res.json();
      if (data.server_time) lastEventTime = data.server_time;
      if (data.events && data.events.length > 0) {
        data.events.forEach((event) => handleEvent(event));
      }
    } catch (e) {
      // silent — next poll will retry
    }
  }

  function disconnect() {
    currentGroupId = null;
    teardown();
    fallbackPolling = false;
    reconnectAttempts = 0;
  }

  function on(eventType, callback) {
    if (!listeners.has(eventType)) listeners.set(eventType, new Set());
    listeners.get(eventType).add(callback);
  }

  function off(eventType, callback) {
    if (listeners.has(eventType)) listeners.get(eventType).delete(callback);
  }

  function handleEvent(event) {
    const { type, payload } = event;
    // Update timestamp watermark so polling doesn't replay old events
    if (event.timestamp) {
      try {
        lastEventTime = Math.max(lastEventTime, new Date(event.timestamp).getTime() / 1000);
      } catch (e) {}
    }
    // Built-in handlers — update badges + toast for common events
    if (type === 'member_joined') {
      UI.toast(`👋 ${payload.full_name} joined the group`, 'info', 3000);
      App.refreshBadges();
    } else if (type === 'message_flagged') {
      UI.toast(`🚩 Message flagged: ${payload.category} (${payload.severity})`, 'warn', 4000);
      App.refreshBadges();
    } else if (type === 'appeal_filed') {
      UI.toast(`⚖️ New appeal filed by user ${payload.user_id}`, 'info', 4000);
      App.refreshBadges();
    } else if (type === 'purgatory_decided') {
      UI.toast(`Purgatory: ${payload.decision} user ${payload.user_id}`, 'info', 3000);
      App.refreshBadges();
    } else if (type === 'mod_action') {
      if (!window.location.hash.includes('modlog')) {
        UI.toast(`${payload.action}: ${payload.reason || ''}`, 'info', 2500);
      }
    } else if (type === 'raid_alert') {
      UI.toast(`🚨 RAID DETECTED — ${payload.join_count} joins in ${payload.window_minutes}min`, 'error', 8000);
      App.refreshBadges();
    } else if (type === 'banned_rejoin') {
      UI.toast(`🚨 Banned user ${payload.full_name} rejoined — auto-re-banned`, 'error', 6000);
    } else if (type === 'settings_changed') {
      UI.toast(`Settings updated: ${payload.fields.join(', ')}`, 'info', 3000);
    }

    // Notify registered listeners
    if (listeners.has(type)) {
      listeners.get(type).forEach((cb) => {
        try { cb(payload); } catch (e) { console.warn('[WS] listener error:', e); }
      });
    }
    if (listeners.has('*')) {
      listeners.get('*').forEach((cb) => {
        try { cb(event); } catch (e) { console.warn('[WS] wildcard listener error:', e); }
      });
    }
  }

  return {
    connect, disconnect, on, off,
    isPolling: () => fallbackPolling,
  };
})();
