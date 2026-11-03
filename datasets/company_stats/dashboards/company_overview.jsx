import React from "react";
import { Controls, VegaChart, useQuery } from "@malloyyo/dashboard";

const ACCENT = "#4f46e5";
const ACCENT_2 = "#06b6d4";

const theme = {
  "--dash-accent": ACCENT,
  "--dash-radius": "12px",
  "--dash-controls-bg": "rgba(79, 70, 229, 0.06)",
  "--edge": "var(--dash-border, #e4e6eb)",
  "--surface": "var(--dash-panel-bg, #ffffff)",
};

const fmt = (n) =>
  n == null ? "–" : Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
const full = (n) => (n == null ? "–" : Intl.NumberFormat("en-US").format(n));

const card = {
  background: "var(--surface)",
  border: "1px solid var(--edge)",
  borderRadius: "var(--dash-radius)",
  padding: 18,
};

function Kpi({ label, value, accent }) {
  return (
    <div style={{ ...card, borderTop: `3px solid ${accent}` }}>
      <div style={{ fontSize: 12, color: "var(--dash-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </div>
      <div style={{ fontSize: 30, fontWeight: 700, marginTop: 6, fontVariantNumeric: "tabular-nums" }}>{value}</div>
    </div>
  );
}

function Card({ title, children, span = 1 }) {
  return (
    <section style={{ ...card, gridColumn: `span ${span}`, minWidth: 0 }}>
      <h2 style={{ margin: "0 0 12px", fontSize: 15, fontWeight: 600 }}>{title}</h2>
      {children}
    </section>
  );
}

const line = (field, color, title) => ({
  width: "container",
  height: 220,
  mark: { type: "area", line: { color }, color, opacity: 0.15, interpolate: "monotone", tooltip: true },
  encoding: {
    x: { field: "period_month", type: "temporal", axis: { title: null, format: "%b %y" } },
    y: { field, type: "quantitative", axis: { title, format: "~s" } },
  },
});

const planBars = {
  width: "container",
  height: 220,
  mark: { type: "bar", color: ACCENT, cornerRadiusEnd: 4, tooltip: true },
  encoding: {
    y: { field: "plan", type: "nominal", sort: "-x", axis: { title: null } },
    x: { field: "total_activity", type: "quantitative", axis: { title: "Activity", format: "~s" } },
  },
};

export default function Dashboard({ dashboard, givens }) {
  const kpis = useQuery({ query: "company_overview", givens });
  const top = useQuery({ query: "top_companies_table", givens });
  const k = kpis.rows?.[0] ?? {};

  return (
    <div style={{ ...theme, maxWidth: 1120, margin: "0 auto", padding: "28px 20px 48px" }}>
      <header style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase", color: ACCENT, fontWeight: 600 }}>
          BasicOps
        </div>
        <h1 style={{ margin: "4px 0 6px", fontSize: 30, lineHeight: 1.15 }}>{dashboard.title}</h1>
        <p style={{ margin: 0, color: "var(--dash-muted)", fontSize: 14 }}>
          Daily per-company activity, signups and plan mix. Test accounts are hidden by default.
        </p>
      </header>

      <div style={{ marginBottom: 20 }}>
        <Controls />
      </div>

      {kpis.error && <p style={{ color: "var(--dash-danger)" }}>{String(kpis.error)}</p>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 14, marginBottom: 14 }}>
        <Kpi label="Activity" value={fmt(k.total_activity)} accent={ACCENT} />
        <Kpi label="New users" value={fmt(k.new_users)} accent={ACCENT_2} />
        <Kpi label="Active companies" value={fmt(k.active_companies)} accent="#f59e0b" />
        <Kpi label="Comments" value={fmt(k.comments)} accent="#10b981" />
        <Kpi label="Chat messages" value={fmt(k.chat_messages)} accent="#ec4899" />
        <Kpi label="New tasks" value={fmt(k.new_tasks)} accent="#8b5cf6" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 14 }}>
        <Card title="Activity by month">
          <VegaChart spec={line("total_activity", ACCENT, "Activity")} query="activity_trend" givens={givens} />
        </Card>
        <Card title="New users by month">
          <VegaChart spec={line("new_users", ACCENT_2, "New users")} query="activity_trend" givens={givens} />
        </Card>
        <Card title="Activity by plan">
          <VegaChart spec={planBars} query="activity_by_plan" givens={givens} />
        </Card>
        <Card title="Top companies by activity">
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--dash-muted)" }}>
                <th style={{ padding: "4px 0" }}>Company</th>
                <th style={{ textAlign: "right" }}>Activity</th>
                <th style={{ textAlign: "right" }}>Users</th>
              </tr>
            </thead>
            <tbody>
              {(top.rows ?? []).map((r) => (
                <tr key={r.company} style={{ borderTop: "1px solid var(--edge)" }}>
                  <td style={{ padding: "6px 0", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.company}
                  </td>
                  <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{full(r.total_activity)}</td>
                  <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{full(r.new_users)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}
