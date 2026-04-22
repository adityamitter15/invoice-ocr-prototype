import { useState, useEffect, useCallback } from "react";
import { api, cachedApi, invalidateCache, reportError } from "../api.js";
import { Icon, icons, fmtCurrency } from "./shared.jsx";

const CONFIDENCE_THRESHOLD = 0.15;

function EditInput({ value, onChange, mono, wide }) {
  return (
    <input
      className={`edit-input${mono ? " mono" : ""}${wide ? " wide" : ""}`}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export default function ReviewQueue({ refresh, onRefresh }) {
  const [subs, setSubs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [approving, setApproving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    cachedApi("/submissions?status=pending_review").then((data) => {
      setSubs(data);
      setSelected((prev) => {
        if (prev && data.some((s) => s.id === prev)) return prev;
        return data.length ? data[0].id : null;
      });
    }).catch((e) => reportError(e, "load queue")).finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load, refresh]);

  const detail = subs.find((s) => s.id === selected) || null;

  useEffect(() => {
    if (!detail) { setDraft(null); setEditing(false); return; }
    setDraft(JSON.parse(JSON.stringify(detail.extracted_data?.structured || {})));
    setEditing(false);
  }, [selected]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleApprove = async () => {
    if (!selected) return;
    setApproving(true);
    try {
      await api(`/submissions/${selected}/approve`, { method: "POST" });
      invalidateCache(
        "/submissions?status=pending_review", "/invoices", "/products",
        "/analytics/summary", "/analytics/monthly-spend", "/analytics/top-products",
        "/analytics/stock-forecast", "/analytics/ocr-confidence",
      );
      setSubs((prev) => {
        const remaining = prev.filter((s) => s.id !== selected);
        setSelected(remaining.length ? remaining[0].id : null);
        return remaining;
      });
      onRefresh?.();
    } catch (e) {
      reportError(e, "approve");
    } finally {
      setApproving(false);
    }
  };

  const handleDelete = async () => {
    if (!selected) return;
    if (!window.confirm("Delete this submission? This cannot be undone.")) return;
    setDeleting(true);
    try {
      await api(`/submissions/${selected}`, { method: "DELETE" });
      invalidateCache(
        "/submissions?status=pending_review",
        "/analytics/summary", "/analytics/ocr-confidence",
      );
      const remaining = subs.filter((s) => s.id !== selected);
      setSubs(remaining);
      setSelected(remaining.length ? remaining[0].id : null);
      onRefresh?.();
    } catch (e) {
      reportError(e, "delete");
    } finally {
      setDeleting(false);
    }
  };

  const handleSaveEdits = async () => {
    if (!selected || !detail) return;
    setSaving(true);
    try {
      const updated = { ...detail.extracted_data, structured: draft };
      await api(`/submissions/${selected}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ extracted_data: updated }),
      });
      invalidateCache("/submissions?status=pending_review");
      setSubs((prev) => prev.map((s) =>
        s.id === selected ? { ...s, extracted_data: updated } : s
      ));
      setEditing(false);
    } catch (e) {
      reportError(e, "save edits");
    } finally {
      setSaving(false);
    }
  };

  const setHeader = (field, value) =>
    setDraft((d) => ({ ...d, [field]: value }));

  const setCustomer = (field, value) =>
    setDraft((d) => ({ ...d, customer: { ...(d.customer || {}), [field]: value } }));

  const setItem = (i, field, value) =>
    setDraft((d) => {
      const items = d.line_items ? [...d.line_items] : [];
      items[i] = { ...items[i], [field]: value };
      return { ...d, line_items: items };
    });

  const addItem = () =>
    setDraft((d) => ({
      ...d,
      line_items: [...(d.line_items || []), { row: (d.line_items?.length || 0) + 1, quantity: "", description: "", unit_price: "", amount: "" }],
    }));

  const removeItem = (i) =>
    setDraft((d) => ({ ...d, line_items: d.line_items.filter((_, idx) => idx !== i) }));

  const structured = editing ? draft : (detail?.extracted_data?.structured || {});
  const items = structured?.line_items || [];

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Review Queue</h1>
          <p className="page-subtitle">{subs.length} invoice{subs.length !== 1 ? "s" : ""} awaiting human review</p>
        </div>
      </header>

      <div className="hitl-banner">
        <div className="hitl-banner-icon">
          <Icon d={icons.queue} size={18} />
        </div>
        <div>
          <strong>Human-in-the-Loop (HITL) Review</strong>
          <p>The OCR pipeline extracts data automatically, and a human verifies every invoice before it enters the system. Correct any misread fields below, then approve to commit to the database.</p>
        </div>
      </div>

      {loading ? (
        <div className="empty-state">
          <p style={{ color: "var(--text-secondary)" }}>Loading queue&hellip;</p>
        </div>
      ) : subs.length === 0 ? (
        <div className="empty-state">
          <Icon d={icons.check} size={48} className="empty-icon" />
          <h3>All caught up</h3>
          <p>No invoices pending review. Upload a new invoice to get started.</p>
        </div>
      ) : (
        <div className="queue-layout">
          <div className="queue-list">
            {subs.map((s) => {
              const ed = s.extracted_data?.structured || {};
              return (
                <button key={s.id}
                  className={`queue-item${s.id === selected ? " active" : ""}`}
                  onClick={() => setSelected(s.id)}>
                  <div className="queue-item-top">
                    <span className="mono">#{ed.invoice_number || s.id?.slice(0, 8)}</span>
                    <span className="badge badge-amber">Pending</span>
                  </div>
                  <div className="queue-item-meta">
                    {ed.customer?.name || "Unknown"} &middot; {ed.line_items?.length || 0} items
                  </div>
                </button>
              );
            })}
          </div>

          {detail && draft && (
            <div className="queue-detail">
              <div className="card">
                <div className="card-header">
                  <h3>
                    Invoice #{structured.invoice_number || "-"}
                    {editing && <span className="badge badge-indigo" style={{ marginLeft: 8 }}>Editing</span>}
                  </h3>
                  <div style={{ display: "flex", gap: 8 }}>
                    {editing ? (
                      <>
                        <button className="btn btn-secondary" onClick={() => { setDraft(JSON.parse(JSON.stringify(detail.extracted_data?.structured || {}))); setEditing(false); }}>
                          Cancel
                        </button>
                        <button className="btn btn-primary" onClick={handleSaveEdits} disabled={saving}>
                          {saving ? "Saving\u2026" : "Save Changes"}
                        </button>
                      </>
                    ) : (
                      <>
                        <button className="btn btn-danger" onClick={handleDelete} disabled={deleting}
                          aria-label="Delete submission">
                          <Icon d={icons.trash} size={15} /> {deleting ? "Deleting\u2026" : "Delete"}
                        </button>
                        <button className="btn btn-secondary" onClick={() => setEditing(true)}
                          aria-label="Edit submission">
                          <Icon d={icons.edit} size={15} /> Edit
                        </button>
                        <button className="btn btn-primary" onClick={handleApprove} disabled={approving}
                          aria-label="Approve and save submission">
                          {approving ? "Approving\u2026" : "Approve & Save"}
                        </button>
                      </>
                    )}
                  </div>
                </div>
                <dl className="detail-grid">
                  <dt>Invoice No</dt>
                  <dd>{editing ? <EditInput value={draft.invoice_number} onChange={(v) => setHeader("invoice_number", v)} mono /> : <span className="mono">{structured.invoice_number || "-"}</span>}</dd>
                  <dt>Date</dt>
                  <dd>{editing ? <EditInput value={draft.invoice_date} onChange={(v) => setHeader("invoice_date", v)} /> : structured.invoice_date || "-"}</dd>
                  <dt>Customer</dt>
                  <dd>{editing ? <EditInput value={draft.customer?.name} onChange={(v) => setCustomer("name", v)} wide /> : structured.customer?.name || "-"}</dd>
                  <dt>Phone</dt>
                  <dd>{editing ? <EditInput value={draft.customer?.phone} onChange={(v) => setCustomer("phone", v)} mono /> : <span className="mono">{structured.customer?.phone || "-"}</span>}</dd>
                  <dt>Net Total</dt>
                  <dd>{editing ? <EditInput value={draft.net_total} onChange={(v) => setHeader("net_total", v)} mono /> : <span className="mono">{structured.net_total ? fmtCurrency(structured.net_total) : "-"}</span>}</dd>
                  <dt>VAT</dt>
                  <dd>{editing ? <EditInput value={draft.vat} onChange={(v) => setHeader("vat", v)} mono /> : structured.vat || "INC"}</dd>
                  <dt>Amount Due</dt>
                  <dd>{editing ? <EditInput value={draft.amount_due} onChange={(v) => setHeader("amount_due", v)} mono /> : <span className="mono highlight">{structured.amount_due ? fmtCurrency(structured.amount_due) : "-"}</span>}</dd>
                </dl>
              </div>

              <div className="card">
                <div className="card-header">
                  <h3>Line Items ({items.length})</h3>
                  {editing && (
                    <button className="btn btn-secondary" onClick={addItem} style={{ fontSize: 12 }}>
                      + Add Row
                    </button>
                  )}
                </div>
                <div className="table-wrap">
                  <table className="table compact">
                    <thead>
                      <tr>
                        <th>#</th><th>Qty</th><th>Description</th>
                        <th className="text-right">Amount</th>
                        {editing && <th></th>}
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((it, i) => {
                        const lowConfidence =
                          typeof it.confidence === "number" && it.confidence < CONFIDENCE_THRESHOLD;
                        return (
                          <tr key={i}>
                            <td className="muted">{it.row || i + 1}</td>
                            <td className="mono">
                              {editing
                                ? <EditInput value={it.quantity} onChange={(v) => setItem(i, "quantity", v)} mono />
                                : it.quantity || "-"}
                            </td>
                            <td>
                              {editing
                                ? <EditInput value={it.description} onChange={(v) => setItem(i, "description", v)} wide />
                                : (
                                  <>
                                    {it.description || "-"}
                                    {lowConfidence && (
                                      <span className="badge badge-amber" style={{ marginLeft: 8 }}
                                        title={`OCR confidence ${(it.confidence * 100).toFixed(0)}%`}>
                                        Low confidence
                                      </span>
                                    )}
                                  </>
                                )}
                            </td>
                            <td className="text-right mono">
                              {editing
                                ? <EditInput value={it.amount} onChange={(v) => setItem(i, "amount", v)} mono />
                                : it.amount ? fmtCurrency(it.amount) : "-"}
                            </td>
                            {editing && (
                              <td>
                                <button className="btn-icon-danger" onClick={() => removeItem(i)}
                                  title="Remove row" aria-label="Remove row">
                                  <Icon d={icons.trash} size={14} />
                                </button>
                              </td>
                            )}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
