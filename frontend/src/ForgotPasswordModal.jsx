// Forgot-password modal launched from the sign-in page. Has two tabs:
// EmailPanel requests a reset link; CodePanel resets with a recovery code.

import { useCallback, useState } from "react";
import PasswordField from "./PasswordField.jsx";
import { isPasswordAcceptable } from "./auth.jsx";
import { API } from "./api.js";

const METHODS = [
  { id: "email", label: "Email me a link" },
  { id: "code",  label: "Use recovery code" },
];

function EmailPanel({ defaultUsername, onClose }) {
  const [username, setUsername] = useState(defaultUsername || "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  const submit = useCallback(async (event) => {
    event.preventDefault();
    if (!username.trim() || submitting) return;
    setError("");
    setSubmitting(true);
    try {
      const res = await fetch(`${API}/auth/request-reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim() }),
      });
      if (!res.ok) {
        let data = {};
        try { data = await res.json(); } catch { /* noop */ }
        throw new Error(data?.detail || "Unable to request reset");
      }
      setSent(true);
    } catch (err) {
      setError(err.message || "Unable to request reset");
    } finally {
      setSubmitting(false);
    }
  }, [username, submitting]);

  if (sent) {
    return (
      <div className="modal-inner">
        <h3 className="modal-inner-title">Check your inbox</h3>
        <p className="modal-sub">
          If an account matches that username, a reset link has been sent to
          the email address on file. The link expires in 15 minutes.
        </p>
        <p className="modal-fine">
          Cannot find the email? Check your spam folder, or switch to the
          recovery code tab to reset immediately.
        </p>
        <div className="modal-actions">
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Back to sign in
          </button>
        </div>
      </div>
    );
  }

  return (
    <form className="modal-inner" onSubmit={submit} noValidate>
      <h3 className="modal-inner-title">Send a reset link</h3>
      <p className="modal-sub">
        We will email a single-use link to the address on file for this
        account. The link expires in 15 minutes.
      </p>

      <label className="modal-field">
        <span className="modal-field-label">Username</span>
        <input
          type="text"
          autoComplete="username"
          autoCapitalize="off"
          spellCheck={false}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          disabled={submitting}
          className="modal-input"
        />
      </label>

      {error && <div className="login-error" role="alert">{error}</div>}

      <div className="modal-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          Cancel
        </button>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!username.trim() || submitting}
        >
          {submitting ? "Sending" : "Email reset link"}
        </button>
      </div>
    </form>
  );
}

function CodePanel({ defaultUsername, onClose }) {
  const [username, setUsername] = useState(defaultUsername || "");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [issuedCode, setIssuedCode] = useState("");

  const passwordOk = isPasswordAcceptable(password);
  const confirmOk = password.length > 0 && password === confirm;
  const canSubmit =
    username.trim().length > 0 &&
    recoveryCode.trim().length > 0 &&
    passwordOk &&
    confirmOk &&
    !submitting;

  const submit = useCallback(async (event) => {
    event.preventDefault();
    if (!canSubmit) return;
    setError("");
    setSubmitting(true);
    try {
      const res = await fetch(`${API}/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: username.trim(),
          recovery_code: recoveryCode.trim(),
          new_password: password,
        }),
      });
      let data = {};
      try { data = await res.json(); } catch { /* noop */ }
      if (!res.ok) throw new Error(data?.detail || "Unable to reset password");
      setIssuedCode(data.recovery_code || "");
    } catch (err) {
      setError(err.message || "Unable to reset password");
    } finally {
      setSubmitting(false);
    }
  }, [canSubmit, username, recoveryCode, password]);

  if (issuedCode) {
    return (
      <div className="modal-inner">
        <h3 className="modal-inner-title">Password reset</h3>
        <p className="modal-sub">
          Your password has been updated. Save the new recovery code below,
          the previous one is no longer valid.
        </p>
        <div className="recovery-surface">
          <span className="recovery-label">New recovery code</span>
          <code className="recovery-code">{issuedCode}</code>
          <button
            type="button"
            className="btn btn-secondary recovery-copy"
            onClick={() => navigator.clipboard?.writeText(issuedCode)}
          >
            Copy code
          </button>
        </div>
        <p className="modal-fine">
          Store this with the same care as your password. It will not be
          shown again.
        </p>
        <div className="modal-actions">
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Back to sign in
          </button>
        </div>
      </div>
    );
  }

  return (
    <form className="modal-inner" onSubmit={submit} noValidate>
      <h3 className="modal-inner-title">Reset with recovery code</h3>
      <p className="modal-sub">
        Enter your recovery code and choose a new password. A fresh code will
        replace the one you use here.
      </p>

      <label className="modal-field">
        <span className="modal-field-label">Username</span>
        <input
          type="text"
          autoComplete="username"
          autoCapitalize="off"
          spellCheck={false}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          disabled={submitting}
          className="modal-input"
        />
      </label>

      <label className="modal-field">
        <span className="modal-field-label">Recovery code</span>
        <input
          type="text"
          autoComplete="one-time-code"
          autoCapitalize="characters"
          spellCheck={false}
          value={recoveryCode}
          onChange={(e) => setRecoveryCode(e.target.value.toUpperCase())}
          disabled={submitting}
          placeholder="XXXX-XXXX-XXXX-XXXX"
          className="modal-input modal-input-mono"
        />
      </label>

      <PasswordField
        id="forgot-new-password"
        label="New password"
        value={password}
        onChange={setPassword}
        autoComplete="new-password"
        disabled={submitting}
        placeholder="Choose a new password"
        showChecklist
        showStrength
      />

      <PasswordField
        id="forgot-confirm-password"
        label="Confirm new password"
        value={confirm}
        onChange={setConfirm}
        autoComplete="new-password"
        disabled={submitting}
        placeholder="Repeat the new password"
      />
      {confirm.length > 0 && !confirmOk && (
        <div className="modal-hint error">Passwords do not match.</div>
      )}

      {error && <div className="login-error" role="alert">{error}</div>}

      <div className="modal-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          Cancel
        </button>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!canSubmit}
        >
          {submitting ? "Resetting" : "Reset password"}
        </button>
      </div>
    </form>
  );
}

export default function ForgotPasswordModal({ defaultUsername, onClose }) {
  const [method, setMethod] = useState("email");

  return (
    <div className="modal-shell" role="dialog" aria-modal="true" aria-labelledby="forgot-title">
      <div className="modal-card modal-card-wide">
        <button
          type="button"
          className="modal-close"
          onClick={onClose}
          aria-label="Close"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        <div className="modal-body">
          <h2 id="forgot-title">Forgot password</h2>
          <p className="modal-sub">
            Choose how you want to regain access. Email is quickest; the
            recovery code works even if email is unavailable.
          </p>

          <div className="modal-tabs" role="tablist" aria-label="Reset method">
            {METHODS.map((m) => (
              <button
                key={m.id}
                type="button"
                role="tab"
                aria-selected={method === m.id}
                className={`modal-tab${method === m.id ? " active" : ""}`}
                onClick={() => setMethod(m.id)}
              >
                {m.label}
              </button>
            ))}
          </div>

          {method === "email"
            ? <EmailPanel defaultUsername={defaultUsername} onClose={onClose} />
            : <CodePanel  defaultUsername={defaultUsername} onClose={onClose} />}
        </div>
      </div>
    </div>
  );
}
