import { useState, useEffect } from "react";
import {
  BarChart, Bar, Line, PieChart, Pie, Cell,
  Area, ComposedChart, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { cachedApi, reportError } from "../api.js";
import { Icon, icons, CHART, fmtCurrency, fmtShort, padMonthly } from "./shared.jsx";

export default function Dashboard({ setView }) {
  const [summary, setSummary] = useState(null);
  const [monthly, setMonthly] = useState([]);
  const [topProducts, setTopProducts] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [pending, setPending] = useState([]);
  const [modelPerf, setModelPerf] = useState(null);

  useEffect(() => {
    cachedApi("/analytics/summary").then(setSummary).catch((e) => reportError(e, "summary"));
    cachedApi("/analytics/monthly-spend").then(setMonthly).catch((e) => reportError(e, "monthly spend"));
    cachedApi("/analytics/top-products").then(setTopProducts).catch((e) => reportError(e, "top products"));
    cachedApi("/invoices").then(setInvoices).catch((e) => reportError(e, "invoices"));
    cachedApi("/submissions?status=pending_review").then(setPending).catch((e) => reportError(e, "pending queue"));
    cachedApi("/analytics/model-performance").then(setModelPerf).catch((e) => reportError(e, "model perf"));
  }, []);

  const kpis = summary ? [
    { label: "Total Invoices", value: summary.total_invoices, icon: icons.invoice, color: "var(--indigo)" },
    { label: "Total Spend", value: fmtCurrency(summary.total_spend), icon: icons.trend, color: "var(--emerald)" },
    { label: "Avg Invoice", value: fmtCurrency(summary.avg_invoice_value), icon: icons.analytics, color: "var(--cyan)" },
    { label: "Pending Review", value: summary.pending_submissions, icon: icons.clock, color: "var(--amber)",
      onClick: () => setView("queue") },
  ] : [];

  const statusData = summary ? [
    { name: "Approved", value: summary.total_invoices, color: CHART.success },
    { name: "Pending", value: summary.pending_submissions, color: CHART.accent },
  ].filter(d => d.value > 0) : [];

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p className="page-subtitle">Overview of your invoice processing pipeline</p>
        </div>
      </header>

      <div className="kpi-grid">
        {kpis.map((k) => (
          <div key={k.label} className={`kpi-card${k.onClick ? " clickable" : ""}`}
            onClick={k.onClick}>
            <div className="kpi-icon" style={{ color: k.color }}>
              <Icon d={k.icon} size={22} />
            </div>
            <div className="kpi-content">
              <span className="kpi-value">{k.value}</span>
              <span className="kpi-label">{k.label}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="charts-row">
        <div className="card chart-card flex-2">
          <h3>Spending Trend</h3>
          {monthly.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart data={padMonthly(monthly)}>
                <defs>
                  <linearGradient id="spendGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={CHART.primary} stopOpacity={0.15} />
                    <stop offset="95%" stopColor={CHART.primary} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="month" tick={{ fontSize: 12 }} stroke="#94a3b8" />
                <YAxis yAxisId="spend" tick={{ fontSize: 12 }} stroke="#94a3b8"
                  tickFormatter={(v) => `\u00A3${v}`} />
                <YAxis yAxisId="count" orientation="right" tick={{ fontSize: 11 }} stroke={CHART.secondary}
                  tickFormatter={(v) => Math.round(v)} allowDecimals={false} />
                <Tooltip formatter={(v, name) => name === "Spend" ? fmtCurrency(v) : v} />
                <Area type="monotone" dataKey="total_spend" name="Spend" yAxisId="spend"
                  stroke={CHART.primary} fill="url(#spendGrad)" strokeWidth={2} />
                <Line type="monotone" dataKey="invoice_count" name="Invoices" yAxisId="count"
                  stroke={CHART.secondary} strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">Upload and approve invoices to see trends</div>
          )}
        </div>

        <div className="card chart-card flex-1">
          <h3>Processing Status</h3>
          {statusData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={statusData} cx="50%" cy="50%" innerRadius={55} outerRadius={85}
                  paddingAngle={4} dataKey="value" nameKey="name">
                  {statusData.map((d, i) => (
                    <Cell key={i} fill={d.color} />
                  ))}
                </Pie>
                <Tooltip formatter={(v) => v} />
                <Legend iconType="circle" />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">No data yet</div>
          )}
        </div>
      </div>

      {topProducts.length > 0 && (
        <div className="card chart-card">
          <h3>Top Products by Revenue</h3>
          <ResponsiveContainer width="100%" height={Math.max(200, topProducts.length * 32 + 40)}>
            <BarChart data={topProducts.slice(0, 10)} layout="vertical"
              margin={{ left: 120 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis type="number" tick={{ fontSize: 11 }} stroke="#94a3b8"
                tickFormatter={(v) => `\u00A3${v}`} />
              <YAxis type="category" dataKey="description" tick={{ fontSize: 11 }}
                stroke="#94a3b8" width={115}
                tickFormatter={(v) => v.length > 20 ? v.slice(0, 20) + "\u2026" : v} />
              <Tooltip formatter={(v) => fmtCurrency(v)} />
              <Bar dataKey="total_spend" name="Revenue" fill={CHART.primary} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {modelPerf && modelPerf.dataset && (
        <div className="card">
          <div className="card-header">
            <h3>Model Training Status</h3>
            <button className="btn-ghost" onClick={() => setView("analytics")}>View details</button>
          </div>
          <div className="model-status-row">
            <div className="model-stat">
              <span className="model-stat-label">Dataset</span>
              <span className="model-stat-value">{modelPerf.dataset.labelled_crops}/{modelPerf.dataset.total_crops} labelled</span>
              <div className="progress-bar-track" style={{ width: 120 }}>
                <div className="progress-bar-fill" style={{
                  width: `${modelPerf.dataset.label_progress}%`,
                  backgroundColor: modelPerf.dataset.label_progress >= 80 ? CHART.success :
                    modelPerf.dataset.label_progress >= 40 ? CHART.accent : CHART.danger
                }} />
              </div>
            </div>
            <div className="model-stat">
              <span className="model-stat-label">Fine-tuned Model</span>
              <span className={`model-stat-value ${modelPerf.has_finetuned_model ? "text-success" : "text-muted"}`}>
                {modelPerf.has_finetuned_model ? "Available" : "Not trained yet"}
              </span>
            </div>
            {modelPerf.evaluation?.finetuned && (
              <>
                <div className="model-stat">
                  <span className="model-stat-label">Character Accuracy</span>
                  <span className="model-stat-value text-success">
                    {((1 - modelPerf.evaluation.finetuned.mean_cer) * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="model-stat">
                  <span className="model-stat-label">CER Improvement</span>
                  <span className="model-stat-value" style={{ color: CHART.primary }}>
                    {(((modelPerf.evaluation.base.mean_cer - modelPerf.evaluation.finetuned.mean_cer) / modelPerf.evaluation.base.mean_cer) * 100).toFixed(1)}%
                  </span>
                </div>
              </>
            )}
            {!modelPerf.evaluation?.finetuned && modelPerf.evaluation?.base && (
              <div className="model-stat">
                <span className="model-stat-label">Base Model CER</span>
                <span className="model-stat-value" style={{ color: CHART.accent }}>
                  {(modelPerf.evaluation.base.mean_cer * 100).toFixed(1)}%
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="charts-row">
        <div className="card flex-1">
          <div className="card-header">
            <h3>Recent Invoices</h3>
            <button className="btn-ghost" onClick={() => setView("invoices")}>View all</button>
          </div>
          <table className="table">
            <thead>
              <tr><th>Invoice</th><th>Customer</th><th>Date</th><th className="text-right">Amount</th></tr>
            </thead>
            <tbody>
              {invoices.slice(0, 5).map((inv) => (
                <tr key={inv.id}>
                  <td className="mono">#{inv.invoice_number || "-"}</td>
                  <td>{inv.customer_name || "-"}</td>
                  <td>{inv.invoice_date || "-"}</td>
                  <td className="text-right mono">{fmtCurrency(inv.amount_due)}</td>
                </tr>
              ))}
              {invoices.length === 0 && (
                <tr><td colSpan={4} className="table-empty">No invoices yet</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card flex-1">
          <div className="card-header">
            <h3>Pending Review</h3>
            <button className="btn-ghost" onClick={() => setView("queue")}>View all</button>
          </div>
          <table className="table">
            <thead>
              <tr><th>ID</th><th>Items</th><th>Submitted</th><th>Status</th></tr>
            </thead>
            <tbody>
              {pending.slice(0, 5).map((s) => {
                const ed = s.extracted_data?.structured || {};
                return (
                  <tr key={s.id} className="clickable" onClick={() => setView("queue")}>
                    <td className="mono">{s.id?.slice(0, 8)}</td>
                    <td>{ed.line_items?.length || 0} items</td>
                    <td>{fmtShort(s.created_at)}</td>
                    <td><span className="badge badge-amber">Pending</span></td>
                  </tr>
                );
              })}
              {pending.length === 0 && (
                <tr><td colSpan={4} className="table-empty">All caught up</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
