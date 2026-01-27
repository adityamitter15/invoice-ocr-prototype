# Database Schema

This directory contains the PostgreSQL schema used for the Invoice OCR prototype.

## Tables
- submissions: stores uploaded invoices and OCR output
- invoice_items: extracted line items from invoices
- products: inventory items
- stock_movements: audit trail for inventory updates

## Usage
1. Run `schema.sql` to create tables
2. Run `seed.sql` to insert test data

PostgreSQL was selected due to the relational nature of invoice data and the need for transactional integrity.