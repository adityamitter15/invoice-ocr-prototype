# AGW Invoice OCR - Frontend

React single-page application for the manager console. Built with Vite.

## Run locally

```bash
npm install
npm run dev
```

Opens on http://localhost:5173. The backend must be running on port 8000 (or
the URL set in `VITE_API_BASE_URL` if overridden).

## Structure

```
src/
  main.jsx               Vite entry, wraps <App> in <AuthProvider>
  App.jsx                Top-level router: login -> reset view -> main app
  auth.jsx               JWT session context and password policy helpers
  api.js                 Fetch wrapper, 401 handling, response cache
  Login.jsx              Sign-in page
  ForgotPasswordModal    Email-link and recovery-code reset tabs
  ChangePasswordModal    In-session password change
  ResetPasswordView      Landing page for the email reset link
  PasswordField          Reusable password input + checklist + strength meter
  components/
    Sidebar              Left navigation
    Dashboard            KPIs, charts, recent activity
    Upload               Drag-and-drop OCR entry point
    ReviewQueue          Human-in-the-loop correction + approval
    Invoices             Searchable approved-invoice list with line items
    Products             Inventory and stock movements
    Analytics            OCR quality, fine-tuning status, BI charts
    ErrorToast           Shared non-blocking error notifier
    shared.jsx           Formatters, chart palette, SVG icon set
```

## Build

```bash
npm run build
```

Produces a static bundle in `dist/` that can be served by any static host.
