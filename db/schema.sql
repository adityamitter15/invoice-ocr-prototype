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
-- Invoice Line Items
-- =========================
CREATE TABLE IF NOT EXISTS invoice_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id UUID REFERENCES submissions(id) ON DELETE CASCADE,
    description TEXT,
    quantity INTEGER,
    amount NUMERIC(10,2),
    confidence NUMERIC(4,3)
);

-- =========================
-- Products (Inventory)
-- =========================
CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    current_stock INTEGER NOT NULL DEFAULT 0
);

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