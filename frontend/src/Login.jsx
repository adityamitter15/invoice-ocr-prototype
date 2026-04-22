import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "./auth.jsx";
import ForgotPasswordModal from "./ForgotPasswordModal.jsx";

function UserIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="11" width="18" height="11" rx="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}

function EyeIcon({ open }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {open ? (
        <>
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
          <circle cx="12" cy="12" r="3" />
        </>
      ) : (
        <>
          <path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a19.7 19.7 0 0 1 5.06-5.94" />
          <path d="M9.9 4.24A10.94 10.94 0 0 1 12 4c7 0 11 8 11 8a19.7 19.7 0 0 1-2.16 3.19" />
          <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
          <path d="M1 1l22 22" />
        </>
      )}
    </svg>
  );
}

export default function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [capsOn, setCapsOn] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [shakeKey, setShakeKey] = useState(0);
  const [forgotOpen, setForgotOpen] = useState(false);
  const usernameRef = useRef(null);

  useEffect(() => { usernameRef.current?.focus(); }, []);

  const canSubmit = username.trim().length > 0 && password.length > 0 && !submitting;

  const handleCapsLock = useCallback((event) => {
    if (typeof event.getModifierState === "function") {
      setCapsOn(event.getModifierState("CapsLock"));
    }
  }, []);

  const onSubmit = useCallback(async (event) => {
    event.preventDefault();
    if (!canSubmit) return;
    setError("");
    setSubmitting(true);
    try {
      await login({ username: username.trim(), password, remember });
    } catch (err) {
      setError(err.message || "Unable to sign in");
      setShakeKey((k) => k + 1);
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  }, [canSubmit, login, username, password, remember]);

  return (
    <>
      <div className="login-shell">
        <div className="login-card" key={shakeKey} data-shake={error ? "1" : "0"}>
          <aside className="login-brand">
            <div className="login-brand-top">
              <img
                src="/agw-logo.jpg"
                alt="AGW Heating"
                className="login-brand-logo"
                width="72"
                height="72"
              />
              <div className="login-brand-text">
                <span className="login-brand-name">AGW Heating</span>
                <span className="login-brand-sub">Manager Console</span>
              </div>
            </div>

            <div className="login-brand-headline">
              <h2>Invoice intelligence for the stockroom.</h2>
              <p>
                Capture supplier invoices, review every extracted field, and
                keep the catalogue accurate without re-keying a line.
              </p>
            </div>

            <dl className="login-brand-stats">
              <div>
                <dt>Handwriting-ready</dt>
                <dd>TrOCR + EasyOCR + Tesseract fallback</dd>
              </div>
              <div>
                <dt>Audit trail</dt>
                <dd>Every approval attributed and timestamped</dd>
              </div>
            </dl>

            <div className="login-brand-footer">
              University of Westminster · BSc Final Year Project
            </div>
          </aside>

          <form className="login-form" onSubmit={onSubmit} noValidate>
            <div className="login-form-header">
              <span className="login-eyebrow">Sign in</span>
              <h1>Welcome back</h1>
              <p>Use your manager credentials to open the console.</p>
            </div>

            <label className="login-field">
              <span className="login-field-label">Username</span>
              <div className="login-input-wrap">
                <span className="login-input-icon"><UserIcon /></span>
                <input
                  ref={usernameRef}
                  type="text"
                  autoComplete="username"
                  spellCheck={false}
                  autoCapitalize="off"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={submitting}
                  placeholder="manager"
                />
              </div>
            </label>

            <label className="login-field">
              <div className="login-field-row">
                <span className="login-field-label">Password</span>
                <button
                  type="button"
                  className="login-link"
                  onClick={() => setForgotOpen(true)}
                  tabIndex={0}
                >
                  Forgot password?
                </button>
              </div>
              <div className="login-input-wrap">
                <span className="login-input-icon"><LockIcon /></span>
                <input
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={handleCapsLock}
                  onKeyUp={handleCapsLock}
                  disabled={submitting}
                  placeholder="Enter your password"
                />
                <button
                  type="button"
                  className="login-input-toggle"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  tabIndex={-1}
                >
                  <EyeIcon open={showPassword} />
                </button>
              </div>
              {capsOn && (
                <div className="login-caps" role="status">Caps Lock is on</div>
              )}
            </label>

            <label className="login-remember">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                disabled={submitting}
              />
              <span>Keep me signed in for a week</span>
            </label>

            {error && (
              <div className="login-error" role="alert">{error}</div>
            )}

            <button
              type="submit"
              className="login-submit"
              disabled={!canSubmit}
            >
              {submitting ? (<><span className="login-spinner" aria-hidden="true" /> Signing in</>) : "Sign in"}
            </button>

            <p className="login-fine">
              Access is restricted to authorised managers. Password policy and
              recovery workflow are enforced server-side.
            </p>
          </form>
        </div>
      </div>

      {forgotOpen && (
        <ForgotPasswordModal
          defaultUsername={username}
          onClose={() => setForgotOpen(false)}
        />
      )}
    </>
  );
}
