import { useState, useEffect, useCallback } from "react";
import { useAuth } from "./auth.jsx";
import Login from "./Login.jsx";
import ChangePasswordModal from "./ChangePasswordModal.jsx";
import ResetPasswordView from "./ResetPasswordView.jsx";
import Sidebar from "./components/Sidebar.jsx";
import Dashboard from "./components/Dashboard.jsx";
import Upload from "./components/Upload.jsx";
import ReviewQueue from "./components/ReviewQueue.jsx";
import Invoices from "./components/Invoices.jsx";
import Products from "./components/Products.jsx";
import Analytics from "./components/Analytics.jsx";
import ErrorToast from "./components/ErrorToast.jsx";
import { cachedApi, configureAuth, reportError } from "./api.js";

function readResetTokenFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search);
    return params.get("reset_token");
  } catch {
    return null;
  }
}

export default function App() {
  const { isAuthenticated, token, user, logout } = useAuth();
  const [view, setView] = useState("dashboard");
  const [pending, setPending] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);
  const [changePwOpen, setChangePwOpen] = useState(false);
  const [resetToken, setResetToken] = useState(() => readResetTokenFromUrl());

  useEffect(() => {
    configureAuth(token, logout);
    return () => configureAuth(null, null);
  }, [token, logout]);

  const loadPending = useCallback(() => {
    if (!isAuthenticated) return;
    cachedApi("/submissions?status=pending_review")
      .then((d) => setPending(d.length))
      .catch((e) => reportError(e, "pending count"));
  }, [isAuthenticated]);

  useEffect(() => { loadPending(); }, [refreshKey, loadPending]);

  if (resetToken) {
    return (
      <>
        <ResetPasswordView
          token={resetToken}
          onDone={() => setResetToken(null)}
        />
        <ErrorToast />
      </>
    );
  }

  if (!isAuthenticated) {
    return (
      <>
        <Login />
        <ErrorToast />
      </>
    );
  }

  return (
    <div className="app-layout">
      <Sidebar
        view={view}
        setView={setView}
        pending={pending}
        user={user}
        onSignOut={logout}
        onChangePassword={() => setChangePwOpen(true)}
      />
      <main className="main-content">
        {view === "dashboard" && <Dashboard setView={setView} />}
        {view === "upload" && <Upload onUploaded={() => setRefreshKey((k) => k + 1)} />}
        {view === "queue" && <ReviewQueue refresh={refreshKey} onRefresh={() => setRefreshKey((k) => k + 1)} />}
        {view === "invoices" && <Invoices />}
        {view === "products" && <Products />}
        {view === "analytics" && <Analytics />}
      </main>
      {changePwOpen && <ChangePasswordModal onClose={() => setChangePwOpen(false)} />}
      <ErrorToast />
    </div>
  );
}
