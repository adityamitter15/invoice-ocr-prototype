// Products page: stock level chart, low-stock warning, searchable product
// list with delete action that cascades through the stock_movements table.

import { useState, useEffect, useCallback } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { api, cachedApi, invalidateCache, reportError } from "../api.js";
import { Icon, icons, CHART } from "./shared.jsx";

export default function Products() {
  const [products, setProducts] = useState([]);
  const [search, setSearch] = useState("");
  const [stockData, setStockData] = useState([]);
  const [deletingId, setDeletingId] = useState(null);

  const load = useCallback(() => {
    cachedApi("/products").then(setProducts).catch((e) => reportError(e, "products"));
    cachedApi("/analytics/stock-forecast").then(setStockData).catch((e) => reportError(e, "stock forecast"));
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleDelete(product) {
    if (!window.confirm(`Delete "${product.name}"?\n\nThis will also remove all stock movements for this product.`)) return;
    setDeletingId(product.id);
    try {
      await api(`/products/${product.id}`, { method: "DELETE" });
      invalidateCache("/products", "/analytics/stock-forecast", "/analytics/top-products", "/analytics/summary");
      load();
    } catch (e) {
      reportError(e, "delete product");
    } finally {
      setDeletingId(null);
    }
  }

  const filtered = products.filter((p) => !search || p.name.toLowerCase().includes(search.toLowerCase()));

  const stockByProduct = {};
  stockData.forEach((m) => {
    if (!stockByProduct[m.name]) stockByProduct[m.name] = { name: m.name, stock: 0, movements: 0 };
    stockByProduct[m.name].stock = m.current_stock;
    stockByProduct[m.name].movements += 1;
  });
  const chartProducts = Object.values(stockByProduct).sort((a, b) => b.stock - a.stock).slice(0, 12);
  const lowStock = products.filter((p) => p.current_stock > 0 && p.current_stock <= 5);

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Products &amp; Inventory</h1>
          <p className="page-subtitle">{products.length} products tracked across all invoices</p>
        </div>
      </header>

      {lowStock.length > 0 && (
        <div className="alert alert-amber">
          <Icon d={icons.alert} size={18} />
          <span><strong>{lowStock.length}</strong> product{lowStock.length > 1 ? "s" : ""} with low stock (5 units or fewer)</span>
        </div>
      )}

      {chartProducts.length > 0 && (
        <div className="card chart-card">
          <h3>Current Stock Levels</h3>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartProducts}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="name" tick={{ fontSize: 10 }} stroke="#94a3b8" angle={-20}
                textAnchor="end" height={60}
                tickFormatter={(v) => v.length > 15 ? v.slice(0, 15) + "\u2026" : v} />
              <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" />
              <Tooltip />
              <Bar dataKey="stock" name="Stock" fill={CHART.primary} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="card">
        <div className="search-bar">
          <Icon d={icons.search} size={16} className="search-icon" />
          <input type="text" placeholder={"Search products\u2026"}
            value={search} onChange={(e) => setSearch(e.target.value)} />
          {search && <span className="search-count">{filtered.length} results</span>}
        </div>
        <table className="table">
          <thead><tr><th>Product Name</th><th className="text-right">Stock Level</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {filtered.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td className="text-right mono">{p.current_stock}</td>
                <td>
                  {p.current_stock === 0 ? <span className="badge badge-slate">No stock</span> :
                   p.current_stock <= 5 ? <span className="badge badge-red">Low</span> :
                   p.current_stock <= 20 ? <span className="badge badge-amber">Medium</span> :
                   <span className="badge badge-green">Good</span>}
                </td>
                <td className="text-right">
                  <button
                    className="btn-icon-danger"
                    onClick={() => handleDelete(p)}
                    disabled={deletingId === p.id}
                    title="Delete product"
                    aria-label={`Delete ${p.name}`}
                  >
                    {deletingId === p.id ? "..." : <Icon d={icons.trash} size={15} />}
                  </button>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={4} className="table-empty">{search ? "No matching products" : "No products yet"}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
