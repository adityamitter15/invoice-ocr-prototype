-- SQLite schema for local fallback (UUID + sensible defaults)

PRAGMA foreign_keys = ON;

-- uuid v4-ish string generator in pure SQLite
-- (not perfectly RFC4122, but unique enough for prototype)
-- format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
-- uses randomblob()
-- Note: SQLite doesn't have CREATE FUNCTION, so we inline this expression as DEFAULT.

CREATE TABLE IF NOT EXISTS submissions (
  id TEXT PRIMARY KEY NOT NULL DEFAULT (
    lower(hex(randomblob(4))) || '-' ||
    lower(hex(randomblob(2))) || '-' ||
    lower(hex(randomblob(2))) || '-' ||
    lower(hex(randomblob(2))) || '-' ||
    lower(hex(randomblob(6)))
  ),
  image_url TEXT NOT NULL,
  extracted_data TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL CHECK (status IN ('pending_review', 'approved')) DEFAULT 'pending_review',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS invoice_items (
  id TEXT PRIMARY KEY NOT NULL DEFAULT (
    lower(hex(randomblob(4))) || '-' ||
    lower(hex(randomblob(2))) || '-' ||
    lower(hex(randomblob(2))) || '-' ||
    lower(hex(randomblob(2))) || '-' ||
    lower(hex(randomblob(6)))
  ),
  submission_id TEXT NOT NULL,
  description TEXT,
  quantity INTEGER,
  amount REAL,
  confidence REAL,
  FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY NOT NULL DEFAULT (
    lower(hex(randomblob(4))) || '-' ||
    lower(hex(randomblob(2))) || '-' ||
    lower(hex(randomblob(2))) || '-' ||
    lower(hex(randomblob(2))) || '-' ||
    lower(hex(randomblob(6)))
  ),
  name TEXT NOT NULL,
  current_stock INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stock_movements (
  id TEXT PRIMARY KEY NOT NULL DEFAULT (
    lower(hex(randomblob(4))) || '-' ||
    lower(hex(randomblob(2))) || '-' ||
    lower(hex(randomblob(2))) || '-' ||
    lower(hex(randomblob(2))) || '-' ||
    lower(hex(randomblob(6)))
  ),
  product_id TEXT NOT NULL,
  submission_id TEXT,
  quantity_change INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (product_id) REFERENCES products(id),
  FOREIGN KEY (submission_id) REFERENCES submissions(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE INDEX IF NOT EXISTS idx_invoice_items_submission_id ON invoice_items(submission_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_product_id ON stock_movements(product_id);