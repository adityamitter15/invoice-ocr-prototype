import { Icon, icons } from "./shared.jsx";

export default function Sidebar({ view, setView, pending, user, onSignOut, onChangePassword }) {
  const nav = [
    { id: "dashboard", label: "Dashboard",      icon: icons.dashboard },
    { id: "upload",    label: "Upload Invoice", icon: icons.upload },
    { id: "queue",     label: "Review Queue",   icon: icons.queue, badge: pending },
    { id: "invoices",  label: "Invoices",       icon: icons.invoice },
    { id: "products",  label: "Products",       icon: icons.product },
    { id: "analytics", label: "Analytics",      icon: icons.analytics },
  ];
  const initial = (user?.username || "?").slice(0, 1).toUpperCase();
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <img src="/agw-logo.jpg" alt="AGW Heating" className="brand-logo" />
        <div className="brand-text">
          <span className="brand-name">AGW Heating</span>
          <span className="brand-sub">Manager Console</span>
        </div>
      </div>
      <nav className="sidebar-nav">
        {nav.map((n) => (
          <button key={n.id} className={`nav-item${view === n.id ? " active" : ""}`}
            onClick={() => setView(n.id)} aria-label={n.label}
            aria-current={view === n.id ? "page" : undefined}>
            <Icon d={n.icon} size={18} />
            <span>{n.label}</span>
            {n.badge > 0 && <span className="nav-badge">{n.badge}</span>}
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        {user && (
          <div className="user-chip">
            <div className="user-avatar">{initial}</div>
            <div className="user-meta">
              <span className="user-name">{user.username}</span>
              <span className="user-role">Manager</span>
            </div>
            <button
              type="button"
              className="user-action"
              onClick={onChangePassword}
              title="Change password"
              aria-label="Change password"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
                strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
            </button>
            <button
              type="button"
              className="user-action"
              onClick={onSignOut}
              title="Sign out"
              aria-label="Sign out"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
                strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </button>
          </div>
        )}
        <div className="engine-badge">
          <span className="engine-dot" />
          TrOCR + EasyOCR + Tesseract
        </div>
      </div>
    </aside>
  );
}
