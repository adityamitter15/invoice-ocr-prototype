// Invoices page: searchable table of every approved invoice with a click-to-
// expand line-item view and a CSV export for accounting hand-off.

import { useState, useEffect, Fragment } from "react";
import { api, cachedApi, reportError } from "../api.js";
import { Icon, icons, fmtCurrency } from "./shared.jsx";

export default function Invoices() {
  const [invoices, setInvoices] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [detail, setDetail] = useState(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    cachedApi("/invoices").then(setInvoices).catch((e) => reportError(e, "invoices"));
  }, []);

  const toggle = async (id) => {
    if (expanded === id) { setExpanded(null); setDetail(null); return; }
    setExpanded(id);
    try {
      setDetail(await api(`/invoices/${id}`));
    } catch (e) {
      setDetail(null);
      reportError(e, "invoice detail");
    }
  };

  const filtered = invoices.filter((inv) => {
    const q = search.toLowerCase();
    return !q || (inv.invoice_number || "").toLowerCase().includes(q) ||
      (inv.customer_name || "").toLowerCase().includes(q);
  });

  const handleExport = () => {
    const rows = [["Invoice", "Date", "Customer", "Net Total", "VAT", "Amount Due"]];
    invoices.forEach((inv) => rows.push([inv.invoice_number, inv.invoice_date, inv.customer_name, inv.net_total, inv.vat, inv.amount_due]));
    const csv = rows.map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = "invoices.csv"; a.click();
  };

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Invoices</h1>
          <p className="page-subtitle">{invoices.length} approved invoice{invoices.length !== 1 ? "s" : ""} in database</p>
        </div>
        <button className="btn btn-secondary" onClick={handleExport}>
          <Icon d={icons.download} size={16} /> Export CSV
        </button>
      </header>

      <div className="card">
        <div className="search-bar">
          <Icon d={icons.search} size={16} className="search-icon" />
          <input type="text" placeholder={"Search by invoice number or customer\u2026"}
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>

        <table className="table">
          <thead>
            <tr>
              <th style={{ width: 32 }}></th>
              <th>Invoice No</th><th>Date</th><th>Customer</th>
              <th className="text-right">Net Total</th><th className="text-right">VAT</th>
              <th className="text-right">Amount Due</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((inv) => (
              <Fragment key={inv.id}>
                <tr className="clickable" onClick={() => toggle(inv.id)}>
                  <td><Icon d={icons.chevron} size={14} className={`expand-icon${expanded === inv.id ? " open" : ""}`} /></td>
                  <td className="mono">#{inv.invoice_number || "-"}</td>
                  <td>{inv.invoice_date || "-"}</td>
                  <td>{inv.customer_name || "-"}</td>
                  <td className="text-right mono">{fmtCurrency(inv.net_total)}</td>
                  <td className="text-right mono">{fmtCurrency(inv.vat)}</td>
                  <td className="text-right mono bold">{fmtCurrency(inv.amount_due)}</td>
                </tr>
                {expanded === inv.id && detail && (
                  <tr className="expand-row">
                    <td colSpan={7}>
                      <div className="expand-content">
                        <h4>Line Items ({detail.items?.length || 0})</h4>
                        <table className="table compact nested">
                          <thead>
                            <tr><th>Qty</th><th>Description</th><th className="text-right">Unit Price</th><th className="text-right">Amount</th></tr>
                          </thead>
                          <tbody>
                            {(detail.items || []).map((it, i) => (
                              <tr key={i}>
                                <td className="mono">{it.quantity || "-"}</td>
                                <td>{it.description || "-"}</td>
                                <td className="text-right mono">{it.unit_price ? fmtCurrency(it.unit_price) : "-"}</td>
                                <td className="text-right mono">{fmtCurrency(it.amount)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="table-empty">{search ? "No matching invoices" : "No invoices yet"}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
