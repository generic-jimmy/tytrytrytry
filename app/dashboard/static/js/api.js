// ============================================================
// API client — wraps fetch with cookie auth, JSON, error handling
// ============================================================

const API = (() => {
  let groupId = null;

  function setGroup(id) { groupId = id; }
  function getGroup() { return groupId; }

  async function request(method, path, body) {
    const opts = {
      method,
      credentials: 'include',
      headers: {},
    };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    if (res.status === 401) {
      window.location.href = '/login';
      throw new Error('Unauthenticated');
    }
    if (res.status === 403) {
      const data = await res.json().catch(() => ({ detail: 'Forbidden' }));
      throw new Error(data.detail || 'Forbidden');
    }
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const data = await res.json();
        if (data.detail) detail = data.detail;
      } catch (e) {}
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  return {
    setGroup,
    getGroup,
    request,  // expose the raw request() for views that need custom endpoints

    listGroups: () => request('GET', '/api/groups'),
    overview: (gid) => request('GET', `/api/groups/${gid || groupId}/overview`),

    listMembers: (gid, params = {}) => {
      const q = new URLSearchParams(params).toString();
      return request('GET', `/api/groups/${gid || groupId}/members${q ? '?' + q : ''}`);
    },
    memberDetail: (gid, userId) => request('GET', `/api/groups/${gid || groupId}/members/${userId}`),
    memberAction: (gid, userId, action) => request('POST', `/api/groups/${gid || groupId}/members/${userId}/${action}`),

    getAIConfig: (gid) => request('GET', `/api/groups/${gid || groupId}/ai-config`),
    updateAIConfig: (gid, payload) => request('PUT', `/api/groups/${gid || groupId}/ai-config`, payload),
    testAIPrompt: (gid, payload) => request('POST', `/api/groups/${gid || groupId}/ai-config/test`, payload),

    listCustomCommands: (gid) => request('GET', `/api/groups/${gid || groupId}/custom-commands`),
    addCustomCommand: (gid, payload) => request('POST', `/api/groups/${gid || groupId}/custom-commands`, payload),
    deleteCustomCommand: (gid, id) => request('DELETE', `/api/groups/${gid || groupId}/custom-commands/${id}`),

    listAutoResponses: (gid) => request('GET', `/api/groups/${gid || groupId}/auto-responses`),
    addAutoResponse: (gid, payload) => request('POST', `/api/groups/${gid || groupId}/auto-responses`, payload),
    updateAutoResponse: (gid, id, payload) => request('PUT', `/api/groups/${gid || groupId}/auto-responses/${id}`, payload),
    deleteAutoResponse: (gid, id) => request('DELETE', `/api/groups/${gid || groupId}/auto-responses/${id}`),

    listScheduled: (gid) => request('GET', `/api/groups/${gid || groupId}/scheduled`),
    addScheduled: (gid, payload) => request('POST', `/api/groups/${gid || groupId}/scheduled`, payload),
    deleteScheduled: (gid, id) => request('DELETE', `/api/groups/${gid || groupId}/scheduled/${id}`),

    listAppeals: (gid, status) => request('GET', `/api/groups/${gid || groupId}/appeals${status ? '?status=' + status : ''}`),
    resolveAppeal: (gid, id, decision, payload) => request('POST', `/api/groups/${gid || groupId}/appeals/${id}/${decision}`, payload || {}),

    listFlags: (gid, status) => request('GET', `/api/groups/${gid || groupId}/flags${status ? '?status=' + status : ''}`),
    resolveFlag: (gid, id, decision) => request('POST', `/api/groups/${gid || groupId}/flags/${id}/${decision}`),

    listPurgatory: (gid, tab) => request('GET', `/api/groups/${gid || groupId}/purgatory${tab ? '?tab=' + tab : ''}`),
    decidePurgatory: (gid, entryId, decision) => request('POST', `/api/groups/${gid || groupId}/purgatory/${entryId}/${decision}`),
    togglePurgatory: (gid, alwaysAllow) => request('POST', `/api/groups/${gid || groupId}/purgatory/toggle`, { always_allow: alwaysAllow }),

    listModlog: (gid, params = {}) => {
      const q = new URLSearchParams(params).toString();
      return request('GET', `/api/groups/${gid || groupId}/modlog${q ? '?' + q : ''}`);
    },
    listAudit: (gid, limit) => request('GET', `/api/groups/${gid || groupId}/audit${limit ? '?limit=' + limit : ''}`),

    analytics: (gid, days) => request('GET', `/api/groups/${gid || groupId}/analytics${days ? '?days=' + days : ''}`),

    listFilters: (gid) => request('GET', `/api/groups/${gid || groupId}/filters`),
    addFilter: (gid, payload) => request('POST', `/api/groups/${gid || groupId}/filters`, payload),
    deleteFilter: (gid, id) => request('DELETE', `/api/groups/${gid || groupId}/filters/${id}`),

    getSettings: (gid) => request('GET', `/api/groups/${gid || groupId}/settings`),
    updateSettings: (gid, payload) => request('PUT', `/api/groups/${gid || groupId}/settings`, payload),

    health: (gid) => request('GET', `/api/groups/${gid || groupId}/health`),
  };
})();
