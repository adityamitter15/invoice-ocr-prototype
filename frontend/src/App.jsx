import { useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

function formatDt(dt) {
  try {
    return new Date(dt).toLocaleString();
  } catch {
    return dt;
  }
}

export default function App() {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [error, setError] = useState("");

  const [loadingQueue, setLoadingQueue] = useState(false);
  const [queue, setQueue] = useState([]);

  const [selected, setSelected] = useState(null);
  const [approving, setApproving] = useState(false);

  const [itemDesc, setItemDesc] = useState("");
  const [itemQty, setItemQty] = useState(1);
  const [itemAmount, setItemAmount] = useState(0);
  const [itemConf, setItemConf] = useState(0.8);

  const selectedRawText = useMemo(() => {
    return selected?.extracted_data?.ocr?.raw_text || "";
  }, [selected]);

  async function fetchQueue() {
    setLoadingQueue(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/submissions?status=pending_review`);
      if (!res.ok) throw new Error(`Queue fetch failed (${res.status})`);
      const data = await res.json();
      setQueue(data);
    } catch (e) {
      setError(e.message || "Failed to load queue");
    } finally {
      setLoadingQueue(false);
    }
  }

  async function fetchSubmission(id) {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/submissions/${id}`);
      if (!res.ok) throw new Error(`Fetch submission failed (${res.status})`);
      const data = await res.json();
      setSelected(data);

      const maybeText = data?.extracted_data?.ocr?.raw_text || "";
      if (maybeText && !itemDesc) setItemDesc(maybeText.slice(0, 80));
    } catch (e) {
      setError(e.message || "Failed to load submission");
    }
  }

  async function handleUpload(e) {
    e.preventDefault();
    if (!file) {
      setError("Choose a file first.");
      return;
    }

    setUploading(true);
    setError("");
    setUploadResult(null);

    try {
      const fd = new FormData();
      fd.append("file", file);

      const res = await fetch(`${API_BASE}/submissions/upload`, {
        method: "POST",
        body: fd,
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Upload failed (${res.status}): ${text}`);
      }

      const data = await res.json();
      setUploadResult(data);
      await fetchQueue();
    } catch (e) {
      setError(e.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleApprove() {
    if (!selected?.id) return;

    setApproving(true);
    setError("");
    try {
      const payload = {
        items: [
          {
            description: itemDesc || "item",
            quantity: Number(itemQty) || 1,
            amount: Number(itemAmount) || 0,
            confidence: Number(itemConf) || 0,
          },
        ],
      };

      const res = await fetch(`${API_BASE}/submissions/${selected.id}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Approve failed (${res.status}): ${text}`);
      }

      setSelected(null);
      setItemDesc("");
      setItemQty(1);
      setItemAmount(0);
      setItemConf(0.8);

      await fetchQueue();
    } catch (e) {
      setError(e.message || "Approve failed");
    } finally {
      setApproving(false);
    }
  }

  useEffect(() => {
    fetchQueue();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="app">
      <header className="header">
        <h1>Invoice OCR — HITL</h1>
        <p>
          Upload → OCR baseline → store as <strong>pending_review</strong> → approve with corrected items.
        </p>
      </header>

      {error ? (
        <div className="alert alert--error" role="alert">
          <strong>Error:</strong> {error}
        </div>
      ) : null}

      <div className="cards">
        <section className="card">
          <h2 className="card__title">1) Upload Invoice</h2>

          <form className="upload-form" onSubmit={handleUpload}>
            <div className="file-wrap">
              <input
                type="file"
                className="file-input"
                accept="image/jpeg,image/png,image/heic,image/heif"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                aria-label="Choose invoice image"
              />
              <button type="submit" className="btn btn--primary" disabled={uploading}>
                {uploading ? "Uploading…" : "Upload"}
              </button>
            </div>
          </form>

          {uploadResult ? (
            <div className="upload-result">
              <div className="upload-result__row">
                <span className="upload-result__label">Submission ID</span>
                <span>{uploadResult.id}</span>
              </div>
              <div className="upload-result__row">
                <span className="upload-result__label">Status</span>
                <span>{uploadResult.status}</span>
              </div>
              <div className="upload-result__row">
                <span className="upload-result__label">Created</span>
                <span>{formatDt(uploadResult.created_at)}</span>
              </div>
              <div className="upload-result__ocr" title="OCR raw text">
                {uploadResult?.extracted_data?.ocr?.raw_text || "(none)"}
              </div>
            </div>
          ) : null}
        </section>

        <section className="card">
          <h2 className="card__title">2) Pending Review Queue</h2>
          <div className="queue-actions">
            <button
              type="button"
              className="btn btn--secondary"
              onClick={fetchQueue}
              disabled={loadingQueue}
            >
              {loadingQueue ? "Refreshing…" : "Refresh"}
            </button>
          </div>

          <div className="queue-list">
            {queue?.length ? (
              queue.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={`queue-item ${selected?.id === s.id ? "queue-item--selected" : ""}`}
                  onClick={() => fetchSubmission(s.id)}
                >
                  <div className="queue-item__head">
                    <span className="queue-item__id">{s.id}</span>
                    <span className="queue-item__date">{formatDt(s.created_at)}</span>
                  </div>
                  <div className="queue-item__preview">
                    {s?.extracted_data?.ocr?.raw_text
                      ? s.extracted_data.ocr.raw_text.slice(0, 120) +
                        (s.extracted_data.ocr.raw_text.length > 120 ? "…" : "")
                      : "(no OCR yet)"}
                  </div>
                </button>
              ))
            ) : (
              <div className="queue-empty">
                {loadingQueue ? "Loading…" : "No pending submissions."}
              </div>
            )}
          </div>
        </section>
      </div>

      <section className="review-section">
        <h2 className="card__title">3) Review & Approve</h2>

        {!selected ? (
          <div className="review-placeholder">
            Select a submission from the queue to review.
          </div>
        ) : (
          <div className="review-grid">
            <div>
              <div className="review-meta">
                <div className="review-meta__row">
                  <span className="review-meta__label">Submission</span>
                  <span>{selected.id}</span>
                </div>
                <div className="review-meta__row">
                  <span className="review-meta__label">Status</span>
                  <span>{selected.status}</span>
                </div>
                <div className="review-meta__row">
                  <span className="review-meta__label">Created</span>
                  <span>{formatDt(selected.created_at)}</span>
                </div>
              </div>
              <div className="review-ocr-box">
                <span className="review-ocr-box__label">OCR raw text</span>
                <div className="review-ocr-box__content">{selectedRawText || "(none)"}</div>
              </div>
            </div>

            <div className="approve-form">
              <p className="approve-form__title">Approve (single line item)</p>
              <div className="approve-form__fields">
                <div className="form-group">
                  <label htmlFor="item-desc">Description</label>
                  <input
                    id="item-desc"
                    value={itemDesc}
                    onChange={(e) => setItemDesc(e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="item-qty">Quantity</label>
                  <input
                    id="item-qty"
                    type="number"
                    value={itemQty}
                    onChange={(e) => setItemQty(e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="item-amount">Amount</label>
                  <input
                    id="item-amount"
                    type="number"
                    step="0.01"
                    value={itemAmount}
                    onChange={(e) => setItemAmount(e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="item-conf">Confidence (0–1)</label>
                  <input
                    id="item-conf"
                    type="number"
                    step="0.01"
                    min="0"
                    max="1"
                    value={itemConf}
                    onChange={(e) => setItemConf(e.target.value)}
                  />
                </div>
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={handleApprove}
                  disabled={approving}
                >
                  {approving ? "Approving…" : "Approve Submission"}
                </button>
              </div>
            </div>
          </div>
        )}
      </section>

      <p className="footer-note">
        Prototype note: HEIC is supported after adding server-side conversion (pillow-heif). Current demo focuses on JPEG/PNG uploads.
      </p>
    </div>
  );
}
