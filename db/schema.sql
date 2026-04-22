-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =========================
-- Submissions (Invoices)
-- =========================
CREATE TABLE IF NOT EXISTS submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_url TEXT NOT NULL,
    extracted_data JSONB,
    status TEXT NOT NULL CHECK (status IN ('pending_review', 'approved')),
    created_at TIMESTAMP DEFAULT NOW()
);

-- =========================
-- Normalized Invoice Records
-- =========================
CREATE TABLE IF NOT EXISTS invoices (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id UUID NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    invoice_number TEXT,
    invoice_date   TEXT,
    customer_name  TEXT,
    customer_phone TEXT,
    net_total      NUMERIC(10,2),
    vat            NUMERIC(10,2),
    amount_due     NUMERIC(10,2),
    created_at     TIMESTAMP DEFAULT NOW()
);

-- =========================
-- Invoice Line Items
-- =========================
CREATE TABLE IF NOT EXISTS invoice_items (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id UUID NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    invoice_id    UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    description   TEXT,
    quantity      INTEGER,
    unit_price    NUMERIC(10,2),
    amount        NUMERIC(10,2),
    confidence    NUMERIC(4,3)
);

-- =========================
-- Products (Inventory)
-- =========================
CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    current_stock INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_products_name ON products(name);

-- =========================
-- Stock Movements (Audit)
-- =========================
CREATE TABLE IF NOT EXISTS stock_movements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID REFERENCES products(id),
    submission_id UUID REFERENCES submissions(id),
    quantity_change INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- =========================
-- Users (Manager authentication)
-- =========================
-- Passwords are stored only as bcrypt hashes (OWASP ASVS V2.4.1, NIST SP 800-63B
-- section 5.1.1.2). The plaintext is never persisted or logged.
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    recovery_code_hash TEXT,
    email TEXT,
    role TEXT NOT NULL CHECK (role IN ('manager')) DEFAULT 'manager',
    created_at TIMESTAMP DEFAULT NOW(),
    last_login_at TIMESTAMP,
    password_changed_at TIMESTAMP
);

-- Short-lived single-use tokens for the email-based reset flow.
-- token_hash stores a SHA-256 of the random token so a DB leak cannot
-- grant live reset capability.
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_reset_tokens_user ON password_reset_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_reset_tokens_expires ON password_reset_tokens(expires_at);