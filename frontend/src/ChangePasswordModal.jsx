// Change-password modal opened from the sidebar by a signed-in user.
// On success it shows the freshly issued recovery code (one-time display).

import { useCallback, useState } from "react";
import PasswordField from "./PasswordField.jsx";
import { isPasswordAcceptable, useAuth } from "./auth.jsx";

export default function ChangePasswordModal({ onClose }) {
  const { authFetch } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [issuedCode, setIssuedCode] = useState("");

  const passwordOk = isPasswordAcceptable(next);
  const confirmOk = next.length > 0 && next === confirm;
  const distinct = current.length === 0 || current !== next;
  const canSubmit =
    current.length > 0 &&
    passwordOk &&
    confirmOk &&
    distinct &&
    !submitting;

  const submit = useCallback(async (event) => {
    event.preventDefault();
    if (!canSubmit) return;
    setError("");
    setSubmitting(true);
    try {
      const data = await authFetch("/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: current,
          new_password: next,
        }),
      });
      setIssuedCode(data?.recovery_code || "");
    } catch (err) {
      setError(err.message || "Unable to change password");
    } finally {
      setSubmitting(false);
    }
  }, [authFetch, canSubmit, current, next]);

  return (
    <div className="modal-shell" role="dialog" aria-modal="true" aria-labelledby="change-title">
      <div className="modal-card">
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

        {issuedCode ? (
          <div className="modal-body">
            <h2 id="change-title">Password changed</h2>
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
              Store this somewhere secure. It is the only way to regain access
              if you forget your password.
            </p>
            <div className="modal-actions">
              <button type="button" className="btn btn-primary" onClick={onClose}>
                Done
              </button>
            </div>
          </div>
        ) : (
          <form className="modal-body" onSubmit={submit} noValidate>
            <h2 id="change-title">Change password</h2>
            <p className="modal-sub">
              Choose a new password. A fresh recovery code will replace the
              previous one once the change is saved.
            </p>

            <PasswordField
              id="change-current-password"
              label="Current password"
              value={current}
              onChange={setCurrent}
              autoComplete="current-password"
              disabled={submitting}
              placeholder="Enter your current password"
            />

            <PasswordField
              id="change-new-password"
              label="New password"
              value={next}
              onChange={setNext}
              autoComplete="new-password"
              disabled={submitting}
              placeholder="Choose a new password"
              showChecklist
              showStrength
            />
            {!distinct && (
              <div className="modal-hint error">New password must differ from the current one.</div>
            )}

            <PasswordField
              id="change-confirm-password"
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
                {submitting ? "Saving" : "Save password"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
