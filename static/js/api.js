/**
 * API helpers for Git Commit Integrator
 */

async function apiRequest(path, options = {}) {
  const opts = {
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
    ...options,
  };
  if (opts.body && typeof opts.body === "object") {
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, opts);
  const raw = await res.text();
  let payload = null;
  try {
    payload = raw ? JSON.parse(raw) : null;
  } catch (e) {
    if (res.status === 403) {
      throw new Error(
        "接口返回 403（非 JSON）。若使用端口 5000，多半被 macOS AirPlay 占用，请改用 python app.py --port 5001 并打开对应地址"
      );
    }
    throw new Error(`Invalid JSON response (${res.status})`);
  }
  if (!payload) {
    throw new Error(`Empty response (${res.status})`);
  }
  if (!res.ok || !payload.ok) {
    const err = new Error(payload.error || `Request failed (${res.status})`);
    err.detail = payload.detail || "";
    err.status = res.status;
    throw err;
  }
  return payload.data;
}

window.GitIntegratorAPI = {
  getRepo: () => apiRequest("/api/repo"),
  setRepo: (path) => apiRequest("/api/repo", { method: "POST", body: { path } }),
  getBranches: () => apiRequest("/api/branches"),
  getAuthors: (source) =>
    apiRequest(`/api/authors?source=${encodeURIComponent(source)}`),
  getCommits: (params) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "") return;
      if (Array.isArray(value)) {
        value.forEach((v) => q.append(key, v));
      } else {
        q.set(key, String(value));
      }
    });
    return apiRequest(`/api/commits?${q.toString()}`);
  },
  getCommitDetail: (hash) => apiRequest(`/api/commits/${encodeURIComponent(hash)}`),
  getStats: (params) => {
    const q = new URLSearchParams();
    if (params.source) q.set("source", params.source);
    (params.hashes || []).forEach((h) => q.append("hash", h));
    return apiRequest(`/api/stats?${q.toString()}`);
  },
  previewConflicts: (body) =>
    apiRequest("/api/integrate/preview", { method: "POST", body }),
  startIntegrate: (body) =>
    apiRequest("/api/integrate", { method: "POST", body }),
  abortIntegrate: (jobId) =>
    apiRequest(`/api/integrate/${encodeURIComponent(jobId)}/abort`, {
      method: "POST",
    }),
  restoreBackup: (body) =>
    apiRequest("/api/backup/restore", { method: "POST", body }),
  streamIntegrate: (jobId, onEvent) => {
    const es = new EventSource(`/api/integrate/${encodeURIComponent(jobId)}/stream`);
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        onEvent(data);
        if (data.type === "done") {
          es.close();
        }
      } catch (e) {
        console.error(e);
      }
    };
    es.onerror = () => {
      es.close();
    };
    return es;
  },
};
