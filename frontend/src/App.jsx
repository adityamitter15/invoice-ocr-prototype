import { useEffect, useMemo, useState } from "react";

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

  const [selected, setSelected] = useState(null); // submission object
  const [approving, setApproving] = useState(false);

  // simple 1-row approve form (prototype)
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

      // prefill approve description with OCR (basic)
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
    <div style={{ fontFamily: "system-ui, -apple-system, Segoe UI, Roboto", padding: 20, maxWidth: 1100, margin: "0 auto" }}>
      <h1 style={{ marginBottom: 6 }}>Invoice OCR Prototype — HITL</h1>
      <p style={{ marginTop: 0, color: "#555" }}>
        Upload → OCR baseline → store as <b>pending_review</b> → approve with corrected items.
      </p>

      {error ? (
        <div style={{ background: "#ffecec", border: "1px solid #ffb3b3", padding: 12, borderRadius: 8, marginBottom: 12 }}>
          <b>Error:</b> {error}
        </div>
      ) : null}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>
        {/* Upload */}
        <div style={{ border: "1px solid #ddd", borderRadius: 10, padding: 14 }}>
          <h2 style={{ marginTop: 0 }}>1) Upload Invoice</h2>

          <form onSubmit={handleUpload}>
            <input
              type="file"
              accept="image/jpeg,image/png,image/heic,image/heif"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <div style={{ height: 10 }} />
            <button type="submit" disabled={uploading} style={{ padding: "8px 12px" }}>
              {uploading ? "Uploading..." : "Upload"}
            </button>
          </form>

          {uploadResult ? (
            <div style={{ marginTop: 12, background: "#f7f7f7", padding: 12, borderRadius: 8 }}>
              <div><b>Submission ID:</b> {uploadResult.id}</div>
              <div><b>Status:</b> {uploadResult.status}</div>
              <div><b>Created:</b> {formatDt(uploadResult.created_at)}</div>
              <div style={{ marginTop: 8 }}>
                <b>OCR raw_text:</b>
                <div style={{ whiteSpace: "pre-wrap", padding: 8, background: "white", border: "1px solid #ddd", borderRadius: 6, marginTop: 6 }}>
                  {uploadResult?.extracted_data?.ocr?.raw_text || "(none)"}
                </div>
              </div>
            </div>
          ) : null}
        </div>

        {/* Queue */}
        <div style={{ border: "1px solid #ddd", borderRadius: 10, padding: 14 }}>
          <h2 style={{ marginTop: 0 }}>2) Pending Review Queue</h2>
          <button onClick={fetchQueue} disabled={loadingQueue} style={{ padding: "6px 10px" }}>
            {loadingQueue ? "Refreshing..." : "Refresh"}
          </button>

          <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
            {queue?.length ? (
              queue.map((s) => (
                <button
                  key={s.id}
                  onClick={() => fetchSubmission(s.id)}
                  style={{
                    textAlign: "left",
                    padding: 10,
                    borderRadius: 10,
                    border: "1px solid #e5e5e5",
                    background: "white",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                    <div style={{ fontWeight: 700, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {s.id}
                    </div>
                    <div style={{ color: "#666", fontSize: 12 }}>{formatDt(s.created_at)}</div>
                  </div>
                  <div style={{ marginTop: 6, color: "#333", fontSize: 13 }}>
                    {s?.extracted_data?.ocr?.raw_text
                      ? s.extracted_data.ocr.raw_text.slice(0, 80) + (s.extracted_data.ocr.raw_text.length > 80 ? "…" : "")
                      : "(no OCR yet)"}
                  </div>
                </button>
              ))
            ) : (
              <div style={{ color: "#666" }}>{loadingQueue ? "Loading…" : "No pending submissions."}</div>
            )}
          </div>
        </div>
      </div>

      {/* Approve panel */}
      <div style={{ marginTop: 16, border: "1px solid #ddd", borderRadius: 10, padding: 14 }}>
        <h2 style={{ marginTop: 0 }}>3) Review & Approve</h2>

        {!selected ? (
          <div style={{ color: "#666" }}>Select a submission from the queue to review.</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div>
              <div><b>Submission:</b> {selected.id}</div>
              <div><b>Status:</b> {selected.status}</div>
              <div><b>Created:</b> {formatDt(selected.created_at)}</div>

              <div style={{ marginTop: 10 }}>
                <b>OCR raw_text</b>
                <div style={{ whiteSpace: "pre-wrap", padding: 10, background: "white", border: "1px solid #ddd", borderRadius: 8, marginTop: 6 }}>
                  {selectedRawText || "(none)"}
                </div>
              </div>
            </div>

            <div>
              <b>Approve (prototype: single line item)</b>
              <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
                <label>
                  Description
                  <input value={itemDesc} onChange={(e) => setItemDesc(e.target.value)} style={{ width: "100%", padding: 8 }} />
                </label>

                <label>
                  Quantity
                  <input type="number" value={itemQty} onChange={(e) => setItemQty(e.target.value)} style={{ width: "100%", padding: 8 }} />
                </label>

                <label>
                  Amount
                  <input type="number" step="0.01" value={itemAmount} onChange={(e) => setItemAmount(e.target.value)} style={{ width: "100%", padding: 8 }} />
                </label>

                <label>
                  Confidence (0-1)
                  <input type="number" step="0.01" min="0" max="1" value={itemConf} onChange={(e) => setItemConf(e.target.value)} style={{ width: "100%", padding: 8 }} />
                </label>

                <button onClick={handleApprove} disabled={approving} style={{ padding: "10px 12px" }}>
                  {approving ? "Approving..." : "Approve Submission"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <p style={{ marginTop: 18, color: "#777", fontSize: 12 }}>
        Prototype note: HEIC is supported after adding server-side conversion (pillow-heif). Current demo focuses on JPEG/PNG uploads.
      </p>
    </div>
  );
}