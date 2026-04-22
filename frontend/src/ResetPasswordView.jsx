import { useCallback, useState } from "react";
import PasswordField from "./PasswordField.jsx";
import { isPasswordAcceptable } from "./auth.jsx";
import { API } from "./api.js";

function dropTokenFromUrl() {
  const url = new URL(window.location.href);
  url.searchParams.delete("reset_token");
  window.history.replaceState({}, "", url.pathname + url.search);
}

export default function ResetPasswordView({ token, onDone }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [issuedCode, setIssuedCode] = useState("");

  const passwordOk = isPasswordAcceptable(password);
  const confirmOk = password.length > 0 && password === confirm;
  const canSubmit = passwordOk && confirmOk && !submitting;

  const submit = useCallback(async (event) => {
    event.preventDefault();
    if (!canSubmit) return;
    setError("");
    setSubmitting(true);
    try {
      const res = await fetch(`${API}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      let data = {};
      try { data = await res.json(); } catch { /* noop */ }
      if (!res.ok) {
        throw new Error(data?.detail || "Unable to reset password");
      }
      setIssuedCode(data.recovery_code || "");
      dropTokenFromUrl();
    } catch (err) {
      setError(err.message || "Unable to reset password");
    } finally {
      setSubmitting(false);
    }
  }, [canSubmit, password, token]);

  const finish = () => {
    dropTokenFromUrl();
    onDone?.();
  };

  return (
    <div className="login-shell">
      <div className="login-card login-card-narrow">
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
              <span className="login-brand-sub">Password Reset</span>
            </div>
          </div>

          <div className="login-brand-headline">
            <h2>{issuedCode ? "All set." : "Choose a new password."}</h2>
            <p>
              {issuedCode
                ? "Your manager account is secured. Keep the new recovery code somewhere safe, the old one is no longer valid."
                : "The link you opened is single-use and expires in a few minutes. Pick a password you have not used elsewhere."}
            </p>
          </div>

          <div className="login-brand-footer">
            University of Westminster · BSc Final Year Project
          </div>
        </aside>

        <div className="login-form">
          {issuedCode ? (
            <>
              <div className="login-form-header">
                <span className="login-eyebrow">Done</span>
                <h1>Password updated</h1>
                <p>You can sign in with your new password.</p>
              </div>
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
                Store this somewhere secure. It is the only break-glass path if
                you lose email access.
              </p>
              <button
                type="button"
                className="login-submit"
                onClick={finish}
              >
                Return to sign in
              </button>
            </>
          ) : (
            <form onSubmit={submit} noValidate>
              <div className="login-form-header">
                <span className="login-eyebrow">Reset password</span>
                <h1>Set a new password</h1>
                <p>Your previous password will stop working immediately.</p>
              </div>

              <div className="login-form-stack">
                <PasswordField
                  id="reset-new-password"
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
                  id="reset-confirm-password"
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

                <button
                  type="submit"
                  className="login-submit"
                  disabled={!canSubmit}
                >
                  {submitting ? (
                    <><span className="login-spinner" aria-hidden="true" /> Saving</>
                  ) : (
                    "Save new password"
                  )}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
