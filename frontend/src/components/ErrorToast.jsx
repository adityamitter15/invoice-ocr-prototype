import { useEffect, useRef, useState } from "react";
import { configureErrorReporter } from "../api.js";

export default function ErrorToast() {
  const [errors, setErrors] = useState([]);
  const timersRef = useRef([]);

  useEffect(() => {
    configureErrorReporter((entry) => {
      const id = `${entry.at}-${Math.random().toString(36).slice(2, 7)}`;
      setErrors((prev) => [...prev, { id, ...entry }]);
      const t = window.setTimeout(() => {
        setErrors((prev) => prev.filter((e) => e.id !== id));
        timersRef.current = timersRef.current.filter((x) => x !== t);
      }, 5000);
      timersRef.current.push(t);
    });
    const timers = timersRef;
    return () => {
      configureErrorReporter(null);
      timers.current.forEach((t) => window.clearTimeout(t));
      timers.current = [];
    };
  }, []);

  if (errors.length === 0) return null;

  return (
    <div className="error-toast-stack" role="alert" aria-live="assertive">
      {errors.map((e) => (
        <div key={e.id} className="error-toast">
          <strong>{e.context || "Error"}</strong>
          <span>{e.message}</span>
          <button
            type="button"
            className="error-toast-close"
            onClick={() => setErrors((prev) => prev.filter((x) => x.id !== e.id))}
            aria-label="Dismiss error"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
