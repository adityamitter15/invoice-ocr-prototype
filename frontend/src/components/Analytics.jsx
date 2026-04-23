// Analytics page: OCR performance (extraction score distribution, engine
// stack, per-submission quality table), model fine-tuning status (dataset
// progress, base-vs-fine-tuned CER, live training-loss curve), and
// business-intelligence views (spend forecast, product frequency).

import { useState, useEffect, useCallback } from "react";
import {
  BarChart, Bar, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, Cell,
} from "recharts";
import { api, cachedApi, reportError } from "../api.js";
import { Icon, icons, CHART, fmtCurrency, padMonthly } from "./shared.jsx";

export default function Analytics() {
  const [confidence, setConfidence] = useState([]);
  const [topProducts, setTopProducts] = useState([]);
  const [monthly, setMonthly] = useState([]);
  const [modelPerf, setModelPerf] = useState(null);

  const loadModelPerf = useCallback(() => {
    // Live fetch so training progress appears immediately without cache delay.
    api("/analytics/model-performance").then(setModelPerf).catch((e) => reportError(e, "model performance"));
  }, []);

  useEffect(() => {
    cachedApi("/analytics/ocr-confidence").then(setConfidence).catch((e) => reportError(e, "ocr confidence"));
    cachedApi("/analytics/top-products").then(setTopProducts).catch((e) => reportError(e, "top products"));
    cachedApi("/analytics/monthly-spend").then(setMonthly).catch((e) => reportError(e, "monthly spend"));
    loadModelPerf();
  }, [loadModelPerf]);

  useEffect(() => {
    const id = setInterval(loadModelPerf, 10_000);
    return () => clearInterval(id);
  }, [loadModelPerf]);

  const confBuckets = [
    { range: "0-25%", count: 0, color: CHART.danger },
    { range: "26-50%", count: 0, color: CHART.accent },
    { range: "51-75%", count: 0, color: CHART.secondary },
    { range: "76-100%", count: 0, color: CHART.success },
  ];
  confidence.forEach((c) => {
    const s = c.extraction_score;
    if (s <= 25) confBuckets[0].count++;
    else if (s <= 50) confBuckets[1].count++;
    else if (s <= 75) confBuckets[2].count++;
    else confBuckets[3].count++;
  });

  const avgScore = confidence.length
    ? Math.round(confidence.reduce((a, c) => a + c.extraction_score, 0) / confidence.length) : 0;

  const forecastData = [...padMonthly(monthly)];
  if (monthly.length >= 1) {
    const last = monthly[monthly.length - 1];
    const trend = monthly.length >= 2
      ? last.total_spend - monthly[monthly.length - 2].total_spend
      : 0;
    forecastData[forecastData.length - 1] = {
      ...last,
      forecast: last.total_spend,
    };
    const [y, m] = last.month.split("-").map(Number);
    for (let i = 1; i <= 3; i++) {
      const nm = m + i > 12 ? m + i - 12 : m + i;
      const ny = m + i > 12 ? y + 1 : y;
      forecastData.push({
        month: `${ny}-${String(nm).padStart(2, "0")}`,
        total_spend: null,
        forecast: Math.max(0, last.total_spend + trend * i),
      });
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Analytics</h1>
          <p className="page-subtitle">OCR performance metrics and business intelligence</p>
        </div>
      </header>

      <div className="section-title">OCR Model Performance</div>
      <div className="charts-row">
        <div className="card chart-card flex-1">
          <h3>Extraction Score Distribution</h3>
          {confidence.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={confBuckets}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="range" tick={{ fontSize: 12 }} stroke="#94a3b8" />
                <YAxis tick={{ fontSize: 12 }} stroke="#94a3b8" allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" name="Submissions">
                  {confBuckets.map((b, i) => <Cell key={i} fill={b.color} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">Process invoices to see metrics</div>
          )}
        </div>

        <div className="card flex-1">
          <h3>Pipeline Stats</h3>
          <div className="stats-grid">
            <div className="stat-item">
              <span className="stat-value">{confidence.length}</span>
              <span className="stat-label">Total Processed</span>
            </div>
            <div className="stat-item">
              <span className="stat-value" style={{ color: avgScore >= 60 ? CHART.success : CHART.accent }}>
                {avgScore}%
              </span>
              <span className="stat-label">Avg Extraction Score</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{confidence.filter((c) => c.extraction_score >= 75).length}</span>
              <span className="stat-label">High Confidence</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{topProducts.length}</span>
              <span className="stat-label">Unique Products</span>
            </div>
          </div>
          <div className="engines-info">
            <h4>OCR Engine Stack</h4>
            <div className="engine-row"><span className="engine-tag trocr">TrOCR</span> Handwritten text (descriptions, customer, date)</div>
            <div className="engine-row"><span className="engine-tag easyocr">EasyOCR</span> Handwritten numerals (amounts, quantities)</div>
            <div className="engine-row"><span className="engine-tag tesseract">Tesseract</span> Printed text (headers, invoice number)</div>
          </div>
        </div>
      </div>

      {modelPerf && (
        <>
          <div className="section-title">Model Fine-tuning</div>
          <div className="charts-row">
            <div className="card flex-1">
              <h3>Training Pipeline</h3>
              {modelPerf.dataset ? (
                <div className="training-pipeline-card">
                  <div className="stats-grid">
                    <div className="stat-item">
                      <span className="stat-value">{modelPerf.dataset.receipts_processed}</span>
                      <span className="stat-label">Receipts Processed</span>
                    </div>
                    <div className="stat-item">
                      <span className="stat-value">{modelPerf.dataset.total_crops}</span>
                      <span className="stat-label">Total Crops</span>
                    </div>
                    <div className="stat-item">
                      <span className="stat-value" style={{ color: modelPerf.dataset.labelled_crops > 0 ? CHART.success : CHART.muted }}>
                        {modelPerf.dataset.labelled_crops}
                      </span>
                      <span className="stat-label">Labelled Crops</span>
                    </div>
                    <div className="stat-item">
                      <span className="stat-value">{modelPerf.dataset.label_progress}%</span>
                      <span className="stat-label">Label Coverage</span>
                    </div>
                  </div>
                  <div className="progress-section">
                    <div className="progress-header">
                      <span>Label Progress</span>
                      <span className="mono">{modelPerf.dataset.labelled_crops}/{modelPerf.dataset.total_crops}</span>
                    </div>
                    <div className="progress-bar-track">
                      <div className="progress-bar-fill" style={{
                        width: `${modelPerf.dataset.label_progress}%`,
                        backgroundColor: modelPerf.dataset.label_progress >= 80 ? CHART.success :
                          modelPerf.dataset.label_progress >= 40 ? CHART.accent : CHART.danger
                      }} />
                    </div>
                  </div>
                  <div className="pipeline-status">
                    <div className={`pipeline-step ${modelPerf.dataset.receipts_processed > 0 ? "done" : ""}`}>
                      <Icon d={modelPerf.dataset.receipts_processed > 0 ? icons.check : icons.clock} size={14} />
                      <span>Build Dataset</span>
                    </div>
                    <div className={`pipeline-step ${modelPerf.dataset.labelled_crops > 50 ? "done" : ""}`}>
                      <Icon d={modelPerf.dataset.labelled_crops > 50 ? icons.check : icons.clock} size={14} />
                      <span>Label Crops ({modelPerf.dataset.labelled_crops > 50 ? "Ready" : "Need 50+"})</span>
                    </div>
                    <div className={`pipeline-step ${modelPerf.has_finetuned_model ? "done" : ""}`}>
                      <Icon d={modelPerf.has_finetuned_model ? icons.check : icons.clock} size={14} />
                      <span>Fine-tune Model</span>
                    </div>
                    <div className={`pipeline-step ${modelPerf.evaluation ? "done" : ""}`}>
                      <Icon d={modelPerf.evaluation ? icons.check : icons.clock} size={14} />
                      <span>Evaluate</span>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="chart-empty">Run build_dataset.py to start</div>
              )}
            </div>

            <div className="card chart-card flex-1">
              <h3>CER Comparison: Base vs Fine-tuned</h3>
              {modelPerf.evaluation && modelPerf.evaluation.base && modelPerf.evaluation.finetuned ? (
                <>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={[
                      {
                        name: "Base TrOCR",
                        cer: +(modelPerf.evaluation.base.mean_cer * 100).toFixed(1),
                        accuracy: +((1 - modelPerf.evaluation.base.mean_cer) * 100).toFixed(1),
                      },
                      {
                        name: "Fine-tuned",
                        cer: +(modelPerf.evaluation.finetuned.mean_cer * 100).toFixed(1),
                        accuracy: +((1 - modelPerf.evaluation.finetuned.mean_cer) * 100).toFixed(1),
                      },
                    ]} layout="vertical" margin={{ left: 90, right: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11 }} stroke="#94a3b8"
                        tickFormatter={(v) => `${v}%`} />
                      <YAxis type="category" dataKey="name" tick={{ fontSize: 12, fontWeight: 600 }}
                        stroke="#94a3b8" width={85} />
                      <Tooltip formatter={(v) => `${v}%`} />
                      <Bar dataKey="accuracy" name="Character Accuracy" fill={CHART.success} radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                  <div className="cer-summary">
                    <div className="cer-metric">
                      <span className="cer-label">Base CER</span>
                      <span className="cer-value" style={{ color: CHART.danger }}>
                        {(modelPerf.evaluation.base.mean_cer * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="cer-metric">
                      <span className="cer-label">Fine-tuned CER</span>
                      <span className="cer-value" style={{ color: CHART.success }}>
                        {(modelPerf.evaluation.finetuned.mean_cer * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="cer-metric">
                      <span className="cer-label">CER Reduction</span>
                      <span className="cer-value" style={{ color: CHART.primary }}>
                        {(((modelPerf.evaluation.base.mean_cer - modelPerf.evaluation.finetuned.mean_cer) / modelPerf.evaluation.base.mean_cer) * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="cer-metric">
                      <span className="cer-label">Exact Match</span>
                      <span className="cer-value" style={{ color: CHART.primary }}>
                        {modelPerf.evaluation.finetuned.word_acc}%
                      </span>
                    </div>
                  </div>
                </>
              ) : modelPerf.evaluation && modelPerf.evaluation.base ? (
                <div className="single-model-result">
                  <div className="stats-grid">
                    <div className="stat-item">
                      <span className="stat-value" style={{ color: CHART.accent }}>
                        {(modelPerf.evaluation.base.mean_cer * 100).toFixed(1)}%
                      </span>
                      <span className="stat-label">Base Model CER</span>
                    </div>
                    <div className="stat-item">
                      <span className="stat-value">
                        {((1 - modelPerf.evaluation.base.mean_cer) * 100).toFixed(1)}%
                      </span>
                      <span className="stat-label">Character Accuracy</span>
                    </div>
                    <div className="stat-item">
                      <span className="stat-value">{modelPerf.evaluation.base.word_acc}%</span>
                      <span className="stat-label">Exact Match</span>
                    </div>
                    <div className="stat-item">
                      <span className="stat-value">{modelPerf.evaluation.base.n_samples}</span>
                      <span className="stat-label">Test Samples</span>
                    </div>
                  </div>
                  <p className="chart-hint">Fine-tune the model to see improvement comparison</p>
                </div>
              ) : (
                <div className="chart-empty">Run evaluate_pipeline.py to see results</div>
              )}
            </div>
          </div>

          {modelPerf.training && modelPerf.training.log_history && modelPerf.training.log_history.length > 0 && (
            <div className="card chart-card">
              <h3>Training Loss Curve</h3>
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={modelPerf.training.log_history.filter(l => l.loss != null).map((l, i) => ({
                  step: l.step || i,
                  loss: +l.loss.toFixed(4),
                }))}>
                  <defs>
                    <linearGradient id="lossGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={CHART.danger} stopOpacity={0.15} />
                      <stop offset="95%" stopColor={CHART.danger} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="step" tick={{ fontSize: 11 }} stroke="#94a3b8" label={{ value: "Training Step", position: "insideBottom", offset: -5, fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" label={{ value: "Loss", angle: -90, position: "insideLeft", fontSize: 11 }} />
                  <Tooltip formatter={(v) => v.toFixed(4)} />
                  <Area type="monotone" dataKey="loss" name="Training Loss"
                    stroke={CHART.danger} fill="url(#lossGrad)" strokeWidth={2} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}

      {confidence.length > 0 && (
        <div className="card">
          <h3>Per-Submission Extraction Quality</h3>
          <table className="table compact">
            <thead>
              <tr><th>Submission</th><th>Status</th><th>Items</th><th>With Amount</th><th>With Desc</th><th>Header</th><th>Score</th></tr>
            </thead>
            <tbody>
              {confidence.map((c) => (
                <tr key={c.submission_id}>
                  <td className="mono">{c.submission_id?.slice(0, 8)}</td>
                  <td><span className={`badge badge-${c.status === "approved" ? "green" : "amber"}`}>
                    {c.status === "approved" ? "Approved" : "Pending"}
                  </span></td>
                  <td className="mono">{c.items_detected}</td>
                  <td className="mono">{c.items_with_amount}</td>
                  <td className="mono">{c.items_with_description}</td>
                  <td className="mono">{c.header_completeness}%</td>
                  <td>
                    <div className="score-bar-wrap">
                      <div className="score-bar-track">
                        <div className="score-bar" style={{ width: `${c.extraction_score}%`,
                          backgroundColor: c.extraction_score >= 75 ? CHART.success :
                            c.extraction_score >= 50 ? CHART.accent : CHART.danger }} />
                      </div>
                      <span className="score-bar-label">{c.extraction_score}%</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="section-title">Business Intelligence</div>
      {forecastData.length > 0 && (
        <div className="card chart-card">
          <h3>Spending Forecast (3-Month Projection)</h3>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={forecastData}>
              <defs>
                <linearGradient id="forecastGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART.accent} stopOpacity={0.1} />
                  <stop offset="95%" stopColor={CHART.accent} stopOpacity={0} />
                </linearGradient>
                <linearGradient id="actualGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART.primary} stopOpacity={0.15} />
                  <stop offset="95%" stopColor={CHART.primary} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="month" tick={{ fontSize: 12 }} stroke="#94a3b8" />
              <YAxis tick={{ fontSize: 12 }} stroke="#94a3b8" tickFormatter={(v) => `\u00A3${v}`} />
              <Tooltip formatter={(v) => v != null ? fmtCurrency(v) : "N/A"} />
              <Area type="monotone" dataKey="total_spend" name="Actual"
                stroke={CHART.primary} fill="url(#actualGrad)" strokeWidth={2} />
              <Area type="monotone" dataKey="forecast" name="Forecast"
                stroke={CHART.accent} fill="url(#forecastGrad)"
                strokeWidth={2} strokeDasharray="6 3" />
              <Legend />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {topProducts.length > 0 && (
        <div className="card chart-card">
          <h3>Product Purchase Frequency</h3>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={topProducts.slice(0, 10)}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="description" tick={{ fontSize: 10 }} stroke="#94a3b8"
                angle={-15} textAnchor="end" height={60}
                tickFormatter={(v) => v.length > 18 ? v.slice(0, 18) + "\u2026" : v} />
              <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" />
              <Tooltip />
              <Bar dataKey="frequency" name="Times Ordered" fill={CHART.secondary} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
