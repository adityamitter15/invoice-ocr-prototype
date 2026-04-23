// Reusable password input. Drives the live policy checklist, strength meter,
// show/hide toggle and the CapsLock-on hint across every password form.

import { useCallback, useMemo, useState } from "react";
import { evaluatePasswordRules, scorePassword } from "./auth.jsx";

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

function LockIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="11" width="18" height="11" rx="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}

export default function PasswordField({
  id,
  label,
  value,
  onChange,
  placeholder,
  autoComplete,
  disabled,
  showChecklist = false,
  showStrength = false,
  showCapsHint = true,
}) {
  const [revealed, setRevealed] = useState(false);
  const [capsOn, setCapsOn] = useState(false);
  const [touched, setTouched] = useState(false);

  const rules = useMemo(() => evaluatePasswordRules(value), [value]);
  const strength = useMemo(() => scorePassword(value), [value]);

  const handleKeyEvent = useCallback((event) => {
    if (typeof event.getModifierState === "function") {
      setCapsOn(event.getModifierState("CapsLock"));
    }
  }, []);

  const visibleChecklist = showChecklist && (touched || value.length > 0);

  return (
    <div className="pwd-field">
      {label && <label className="pwd-field-label" htmlFor={id}>{label}</label>}
      <div className="pwd-input-wrap">
        <span className="pwd-input-icon"><LockIcon /></span>
        <input
          id={id}
          type={revealed ? "text" : "password"}
          autoComplete={autoComplete}
          value={value}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setTouched(true)}
          onKeyDown={handleKeyEvent}
          onKeyUp={handleKeyEvent}
        />
        <button
          type="button"
          className="pwd-input-toggle"
          onClick={() => setRevealed((v) => !v)}
          aria-label={revealed ? "Hide password" : "Show password"}
          tabIndex={-1}
        >
          <EyeIcon open={revealed} />
        </button>
      </div>

      {showStrength && (
        <div className="pwd-meta">
          <div className="pwd-strength">
            {[1, 2, 3, 4].map((i) => (
              <span
                key={i}
                className={`pwd-strength-bar s${Math.min(strength.score, 4)}`}
                data-active={value && i <= strength.score ? "1" : "0"}
              />
            ))}
          </div>
          <span className="pwd-strength-label">{value ? strength.label : "\u00A0"}</span>
        </div>
      )}

      {showCapsHint && capsOn && (
        <div className="pwd-caps" role="status">Caps Lock is on</div>
      )}

      {visibleChecklist && (
        <ul className="pwd-rules" aria-live="polite">
          {rules.map((rule) => (
            <li key={rule.id} data-passed={rule.passed ? "1" : "0"}>
              <span className="pwd-rule-mark" aria-hidden="true">
                {rule.passed ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="9" />
                  </svg>
                )}
              </span>
              <span>{rule.label}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
