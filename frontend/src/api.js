export const API = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

const SESSION_KEY = "agw.auth.session";

let _onUnauthorized = null;
let _onError = null;

function readSessionToken() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.token || !parsed?.expiresAt) return null;
    if (Date.parse(parsed.expiresAt) <= Date.now()) return null;
    return parsed.token;
  } catch {
    return null;
  }
}

export function configureAuth(_token, onUnauthorized) {
  // Token is read directly from sessionStorage on every request; the arg is
  // accepted for backwards compatibility but intentionally ignored.
  _onUnauthorized = onUnauthorized;
}

export function configureErrorReporter(fn) {
  _onError = fn;
}

export function reportError(err, context) {
  const msg = err?.message || String(err);
  if (_onError) {
    _onError({ message: msg, context, at: Date.now() });
  } else if (typeof window !== "undefined" && window.console) {
    // Fallback used only before ErrorToast mounts.
    // eslint-disable-next-line no-console
    window.console.error(context ? `[${context}]` : "", err);
  }
}

export async function api(path, opts = {}) {
  const headers = new Headers(opts.headers || {});
  const token = readSessionToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res;
  try {
    res = await fetch(`${API}${path}`, { ...opts, headers });
  } catch (err) {
    reportError(err, `fetch ${path}`);
    throw err;
  }
  if (res.status === 401) {
    if (_onUnauthorized) _onUnauthorized();
    const err = new Error("Session expired");
    err.status = 401;
    throw err;
  }
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* noop */ }
    const err = new Error(detail || `${res.status} ${res.statusText}`);
    err.status = res.status;
    reportError(err, `API ${path}`);
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

const _cache = {};
const CACHE_TTL = 5 * 60 * 1000;

export function cachedApi(path) {
  const entry = _cache[path];
  if (entry && Date.now() - entry.ts < CACHE_TTL) return Promise.resolve(entry.data);
  return api(path).then((data) => { _cache[path] = { data, ts: Date.now() }; return data; });
}

export function invalidateCache(...paths) {
  for (const p of paths) delete _cache[p];
}
