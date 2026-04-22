import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { API } from "./api.js";

const STORAGE_KEY = "agw.auth.session";

const AuthContext = createContext(null);

function readSession() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.token || !parsed?.expiresAt) return null;
    if (Date.parse(parsed.expiresAt) <= Date.now()) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeSession(session) {
  if (session) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  else sessionStorage.removeItem(STORAGE_KEY);
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(readSession);

  const logout = useCallback(() => {
    writeSession(null);
    setSession(null);
  }, []);

  useEffect(() => {
    if (!session?.expiresAt) return;
    const msUntilExpiry = Date.parse(session.expiresAt) - Date.now();
    // Defer to a timer (even at 0ms) so we never call setState synchronously
    // inside the effect, which causes cascading renders.
    const timer = window.setTimeout(logout, Math.max(0, msUntilExpiry));
    return () => window.clearTimeout(timer);
  }, [session, logout]);

  const login = useCallback(async ({ username, password, remember }) => {
    const res = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, remember }),
    });

    if (!res.ok) {
      let detail = "Invalid credentials";
      try {
        const body = await res.json();
        if (body?.detail) detail = body.detail;
      } catch { /* noop */ }
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }

    const data = await res.json();
    const next = {
      token: data.access_token,
      expiresAt: data.expires_at,
      user: data.user,
    };
    writeSession(next);
    setSession(next);
    return next;
  }, []);

  const authFetch = useCallback(async (path, opts = {}) => {
    const headers = new Headers(opts.headers || {});
    if (session?.token) headers.set("Authorization", `Bearer ${session.token}`);
    const res = await fetch(`${API}${path}`, { ...opts, headers });
    if (res.status === 401) {
      logout();
      throw new Error("Session expired, please sign in again");
    }
    if (!res.ok) {
      let detail = "";
      try {
        const body = await res.json();
        if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      } catch { /* noop */ }
      throw new Error(detail || `${res.status} ${res.statusText}`);
    }
    if (res.status === 204) return null;
    return res.json();
  }, [session, logout]);

  const value = useMemo(() => ({
    user: session?.user || null,
    token: session?.token || null,
    isAuthenticated: Boolean(session?.token),
    login,
    logout,
    authFetch,
  }), [session, login, logout, authFetch]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}

// Length gate is duplicated server-side in app/auth.py#evaluate_password_rules.
const MIN_PASSWORD_LENGTH = 12;

const COMMON_PASSWORDS = new Set([
  "password", "password1", "password123", "passw0rd", "qwerty", "qwerty123",
  "123456", "12345678", "1234567890", "111111", "000000", "letmein", "welcome",
  "admin", "admin123", "root", "toor", "iloveyou", "monkey", "dragon",
  "baseball", "football", "superman", "batman", "princess", "sunshine",
  "master", "shadow", "michael", "changeme",
]);

export function evaluatePasswordRules(password) {
  const p = password || "";
  return [
    { id: "length", label: `At least ${MIN_PASSWORD_LENGTH} characters`, passed: p.length >= MIN_PASSWORD_LENGTH },
    { id: "upper",  label: "An uppercase letter (A-Z)",                   passed: /[A-Z]/.test(p) },
    { id: "lower",  label: "A lowercase letter (a-z)",                    passed: /[a-z]/.test(p) },
    { id: "digit",  label: "A number (0-9)",                              passed: /\d/.test(p) },
    { id: "symbol", label: "A special character",                         passed: /[^A-Za-z0-9]/.test(p) },
    { id: "common", label: "Not a commonly used password",                passed: p.length > 0 && !COMMON_PASSWORDS.has(p.toLowerCase()) },
  ];
}

export function isPasswordAcceptable(password) {
  return evaluatePasswordRules(password).every((r) => r.passed);
}

export function scorePassword(password) {
  if (!password) return { score: 0, label: "" };
  const rules = evaluatePasswordRules(password);
  const lengthOk = rules.find((r) => r.id === "length").passed;
  if (!lengthOk) return { score: 1, label: "Too short" };

  const passed = rules.filter((r) => r.passed).length;
  if (passed <= 3) return { score: 1, label: "Too weak" };
  if (passed === 4) return { score: 2, label: "Getting there" };
  if (passed === 5) return { score: 3, label: "Strong" };
  return { score: 4, label: "Excellent" };
}
