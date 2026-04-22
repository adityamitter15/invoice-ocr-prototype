import { useState, useRef } from "react";
import { api, invalidateCache, reportError } from "../api.js";
import { Icon, icons, CHART, fmtCurrency } from "./shared.jsx";

export default function Upload({ onUploaded }) {
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const inputRef = useRef();

  const handleDrop = (e) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (!f) return;
    if (!f.type.startsWith("image/")) {
      setError("Only image files (JPG, PNG, HEIC) are supported.");
      return;
    }
    setError(null);
    setFile(f);
  };

  const openPicker = () => inputRef.current?.click();

  const handleKey = (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openPicker();
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true); setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api("/submissions/upload", { method: "POST", body: fd });
      setResult(res);
      invalidateCache("/submissions?status=pending_review", "/analytics/summary", "/analytics/ocr-confidence");
      onUploaded?.();
    } catch (e) {
      setError(e.message);
      reportError(e, "upload");
    } finally {
      setUploading(false);
    }
  };

  const structured = result?.extracted_data?.structured || {};
  const items = structured.line_items || [];
  const headerScore = [structured.invoice_number, structured.invoice_date,
    structured.customer?.name, structured.amount_due].filter(Boolean).length;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Upload Invoice</h1>
          <p className="page-subtitle">Drop a receipt image to run the OCR pipeline</p>
        </div>
      </header>

      {!result ? (
        <div className="upload-layout">
          <div className="upload-main">
            <label className={`dropzone${dragging ? " dragover" : ""}`}
              tabIndex={0}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
              onKeyDown={handleKey}>
              <input ref={inputRef} type="file" accept="image/*" hidden
                onChange={(e) => { const f = e.target.files?.[0]; if (f) setFile(f); }} />
              <div className="dropzone-icon">
                <Icon d={icons.upload} size={44} />
              </div>
              {file ? (
                <div className="dropzone-file">
                  <span className="file-name">{file.name}</span>
                  <span className="file-size">{(file.size / 1024).toFixed(0)} KB</span>
                </div>
              ) : (
                <>
                  <p className="dropzone-text">Drag and drop an invoice image here</p>
                  <p className="dropzone-hint">or click to browse</p>
                </>
              )}
            </label>

            <div className="upload-meta">
              <span><strong>JPG</strong>, <strong>PNG</strong> or <strong>HEIC</strong></span>
              <span>Up to <strong>10&nbsp;MB</strong></span>
              <span>~<strong>20&ndash;35&nbsp;s</strong> per invoice</span>
            </div>

            {file && !uploading && (
              <button className="btn btn-primary upload-btn" onClick={handleUpload}>
                Process Invoice
              </button>
            )}
            {uploading && (
              <div className="progress-wrap" role="status" aria-live="polite">
                <span className="progress-spinner" aria-hidden="true" />
                <span className="progress-label">Extracting&hellip;</span>
              </div>
            )}
            {error && <div className="error-msg">{error}</div>}
          </div>

          <aside className="upload-sidebar">
            <h3>What happens after upload</h3>
            <ol className="pipeline-steps">
              <li>
                <span className="step-num">1</span>
                <div>
                  <strong>Normalise &amp; segment</strong>
                  <p>The image is deskewed, grid lines are removed, and the invoice is split into header, table and footer regions.</p>
                </div>
              </li>
              <li>
                <span className="step-num">2</span>
                <div>
                  <strong>Multi-engine OCR</strong>
                  <p>Printed text goes to Tesseract, cursive handwriting to TrOCR, and isolated digits to EasyOCR.</p>
                </div>
              </li>
              <li>
                <span className="step-num">3</span>
                <div>
                  <strong>Confidence scoring</strong>
                  <p>Each cell gets a confidence score derived from the model&apos;s own token probabilities. Low-confidence fields are flagged for review.</p>
                </div>
              </li>
              <li>
                <span className="step-num">4</span>
                <div>
                  <strong>Review &amp; approve</strong>
                  <p>Open the Review Queue to correct any misreads, then approve to commit the invoice to the database atomically.</p>
                </div>
              </li>
            </ol>

            <div className="upload-tips">
              <strong>Tips for best accuracy</strong>
              <ul>
                <li>Photograph the invoice flat against a dark surface.</li>
                <li>Bright, even lighting &mdash; avoid shadows across the page.</li>
                <li>Include the full page so header and footer are captured.</li>
              </ul>
            </div>
          </aside>
        </div>
      ) : (
        <div className="result-area">
          <div className="result-header">
            <div className="result-success">
              <Icon d={icons.check} size={20} />
              <span>Invoice processed successfully</span>
            </div>
            <button className="btn btn-secondary" onClick={() => {
              setResult(null); setFile(null);
            }}>Upload Another</button>
          </div>

          <div className="extraction-score-card">
            <div className="score-ring">
              <svg viewBox="0 0 36 36" className="score-svg">
                <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  fill="none" stroke="#e2e8f0" strokeWidth="3" />
                <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  fill="none" stroke={headerScore >= 3 ? CHART.success : CHART.accent}
                  strokeWidth="3" strokeDasharray={`${headerScore * 25}, 100`} />
              </svg>
              <span className="score-value">{headerScore * 25}%</span>
            </div>
            <div className="score-detail">
              <h4>Header Extraction</h4>
              <div className="score-fields">
                {[
                  ["Invoice No", structured.invoice_number],
                  ["Date", structured.invoice_date],
                  ["Customer", structured.customer?.name],
                  ["Amount Due", structured.amount_due],
                ].map(([label, val]) => (
                  <div key={label} className={`score-field ${val ? "found" : "missing"}`}>
                    <Icon d={val ? icons.check : icons.x} size={14} />
                    <span>{label}: {val || "Not detected"}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="cards-row">
            <div className="card">
              <h3>Invoice Details</h3>
              <dl className="detail-grid">
                <dt>Invoice No</dt><dd className="mono">{structured.invoice_number || "-"}</dd>
                <dt>Date</dt><dd>{structured.invoice_date || "-"}</dd>
                <dt>Customer</dt><dd>{structured.customer?.name || "-"}</dd>
                <dt>Phone</dt><dd className="mono">{structured.customer?.phone || "-"}</dd>
                <dt>Net Total</dt><dd className="mono">{structured.net_total ? fmtCurrency(structured.net_total) : "-"}</dd>
                <dt>VAT</dt><dd className="mono">{structured.vat || "-"}</dd>
                <dt>Amount Due</dt><dd className="mono highlight">{structured.amount_due ? fmtCurrency(structured.amount_due) : "-"}</dd>
              </dl>
            </div>
            <div className="card flex-2">
              <h3>Line Items ({items.length})</h3>
              <div className="table-wrap">
                <table className="table compact">
                  <thead>
                    <tr><th>#</th><th>Qty</th><th>Description</th><th className="text-right">Amount</th></tr>
                  </thead>
                  <tbody>
                    {items.map((it, i) => (
                      <tr key={i}>
                        <td className="muted">{it.row || i + 1}</td>
                        <td className="mono">{it.quantity || "-"}</td>
                        <td>{it.description || "-"}</td>
                        <td className="text-right mono">{it.amount ? fmtCurrency(it.amount) : "-"}</td>
                      </tr>
                    ))}
                    {items.length === 0 && (
                      <tr><td colSpan={4} className="table-empty">No line items detected</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
