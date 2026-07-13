// ============================================================
// WebSocket client — real-time updates without polling
// ============================================================

const WS = (() => {
  let socket = null;
  let reconnectAttempts = 0;
  let reconnectTimer = null;
  let pingTimer = null;
  let currentGroupId = null;
  const listeners = new Map(); // event_type -> Set<callback>

  function connect(groupId) {
    if (currentGroupId === groupId && socket && socket.readyState === WebSocket.OPEN) return;
    currentGroupId = groupId;
    if (socket) {
      try { socket.close(); } catch (e) {}
    }

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/api/ws?group_id=${groupId}`;
    try {
      socket = new WebSocket(url);
    } catch (e) {
      console.warn('WebSocket construction failed, falling back to polling', e);
      scheduleReconnect();
      return;
    }

    socket.onopen = () => {
      reconnectAttempts = 0;
      console.log('[WS] connected to group', groupId);
      // Send periodic pings to keep the connection alive (some load
      // balancers/proxies close idle WS connections after 30-60s).
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
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectAttempts++;
    if (reconnectAttempts > 10) {
      console.warn('[WS] giving up after 10 attempts — falling back to polling');
      return;
    }
    const delay = Math.min(30000, 1000 * Math.pow(2, reconnectAttempts));
    console.log(`[WS] reconnecting in ${delay}ms (attempt ${reconnectAttempts})`);
    reconnectTimer = setTimeout(() => {
      if (currentGroupId) connect(currentGroupId);
    }, delay);
  }

  function disconnect() {
    currentGroupId = null;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
    if (socket) {
      try { socket.close(); } catch (e) {}
      socket = null;
    }
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
      // Subtle toast for mod actions — only show if not on the modlog page
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
    // Also fire to '*' wildcard listeners
    if (listeners.has('*')) {
      listeners.get('*').forEach((cb) => {
        try { cb(event); } catch (e) { console.warn('[WS] wildcard listener error:', e); }
      });
    }
  }

  return { connect, disconnect, on, off };
})();
