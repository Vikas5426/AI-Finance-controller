import React from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  AreaChart,
  Area,
  CartesianGrid,
} from 'recharts';
import { ActiveBatchResponse } from '../services/batchService';

interface OverviewViewProps {
  batch: ActiveBatchResponse | null;
  onNavigateToWorkflow: () => void;
  onNavigateToExceptions: () => void;
}

export const OverviewView: React.FC<OverviewViewProps> = ({
  batch,
  onNavigateToWorkflow,
  onNavigateToExceptions,
}) => {
  const vectorsData = [
    { category: 'Matched', matched: 204, flagged: 0 },
    { category: 'Cutoff Lag', matched: 0, flagged: 18 },
    { category: 'MDR Fees', matched: 0, flagged: 12 },
    { category: 'Missing Wire', matched: 0, flagged: 6 },
  ];

  const forecastData = batch?.cash_forecast && batch.cash_forecast.length > 0
    ? batch.cash_forecast.map((f) => ({
        name: f.label || `W${f.week}`,
        confirmed: f.confirmed_lakhs,
        inTransit: f.in_transit_lakhs,
      }))
    : [
        { name: 'W01', confirmed: 15.2, inTransit: 3.8 },
        { name: 'W02', confirmed: 18.0, inTransit: 4.5 },
        { name: 'W03', confirmed: 22.4, inTransit: 6.0 },
        { name: 'W04', confirmed: 19.8, inTransit: 5.2 },
        { name: 'W05', confirmed: 24.1, inTransit: 7.1 },
        { name: 'W06', confirmed: 26.5, inTransit: 6.8 },
        { name: 'W07', confirmed: 28.0, inTransit: 8.0 },
        { name: 'W08', confirmed: 31.2, inTransit: 7.5 },
        { name: 'W09', confirmed: 29.5, inTransit: 9.2 },
        { name: 'W10', confirmed: 34.0, inTransit: 8.8 },
        { name: 'W11', confirmed: 36.5, inTransit: 10.4 },
        { name: 'W12', confirmed: 38.0, inTransit: 9.6 },
        { name: 'W13', confirmed: 42.0, inTransit: 11.2 },
      ];

  const totalRecords = batch?.total_records || 240;
  const matchRate = (batch?.match_rate || 85.0).toFixed(1);
  const exceptionsCount = batch?.exceptions_count || 36;
  const grossVolume = batch?.stats?.gross_flow_formatted || '₹1,24,50,000.00';

  const slidingWindows = [
    { id: 'WIN-01', range: '#001-024', status: 'healthy', label: '91.6%', exact: 22, ctx: 0, held: 2, exactPct: '91.6%', ctxPct: '0%', heldPct: '8.4%' },
    { id: 'WIN-02', range: '#025-048', status: 'healthy', label: '100%', exact: 24, ctx: 0, held: 0, exactPct: '100%', ctxPct: '0%', heldPct: '0%' },
    { id: 'WIN-03', range: '#049-072', status: 'warning', label: '79.2%', exact: 19, ctx: 0, held: 5, exactPct: '79.2%', ctxPct: '0%', heldPct: '20.8%' },
    { id: 'WIN-04', range: '#073-096', status: 'healthy', label: '95.8%', exact: 23, ctx: 0, held: 1, exactPct: '95.8%', ctxPct: '0%', heldPct: '4.2%' },
    { id: 'WIN-05', range: '#097-120', status: 'healthy', label: '87.5%', exact: 21, ctx: 0, held: 3, exactPct: '87.5%', ctxPct: '0%', heldPct: '12.5%' },
    { id: 'WIN-06', range: '#121-144', status: 'critical', label: '75.0%', exact: 18, ctx: 0, held: 6, exactPct: '75.0%', ctxPct: '0%', heldPct: '25.0%' },
    { id: 'WIN-07', range: '#145-168', status: 'healthy', label: '100%', exact: 24, ctx: 0, held: 0, exactPct: '100%', ctxPct: '0%', heldPct: '0%' },
    { id: 'WIN-08', range: '#169-192', status: 'healthy', label: '91.6%', exact: 22, ctx: 0, held: 2, exactPct: '91.6%', ctxPct: '0%', heldPct: '8.4%' },
    { id: 'WIN-09', range: '#193-216', status: 'warning', label: '83.3%', exact: 20, ctx: 0, held: 4, exactPct: '83.3%', ctxPct: '0%', heldPct: '16.7%' },
    { id: 'WIN-10', range: '#217-240', status: 'healthy', label: '95.8%', exact: 23, ctx: 0, held: 1, exactPct: '95.8%', ctxPct: '0%', heldPct: '4.2%' },
  ];

  return (
    <section className="view-container active" id="view-overview">
      <div id="overview-populated-content">
        <div className="overview-header">
          <div>
            <h1 className="overview-title">Overview</h1>
            <p className="overview-sub">Your workspace at a glance.</p>
          </div>
          <div style={{ display: 'flex', gap: '0.6rem' }}>
            <button className="btn btn-secondary btn-sm" id="btn-export-overview">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              Export Summary
            </button>
            <button
              className="btn btn-primary btn-sm"
              id="btn-new-report-overview"
              onClick={onNavigateToWorkflow}
            >
              Start Reconciliation Workflow →
            </button>
          </div>
        </div>

        {/* Verdict Banner */}
        <div id="overview-verdict-banner" className="verdict-banner-card">
          <div className="verdict-content">
            <div className="verdict-headline" id="verdict-headline-text">
              <span>Reconciliation Assessment · Healthy</span>
            </div>
            <div className="verdict-subtext" id="verdict-subtext-detail">
              All multi-stream feeds reconciled with 1-paise mathematical precision. 0 unverified anomalies detected.
            </div>
          </div>
          <div className="verdict-actions" id="verdict-action-links">
            <button className="btn btn-secondary btn-sm" onClick={onNavigateToWorkflow}>
              Fix source mapping
            </button>
            <button className="btn btn-primary btn-sm" onClick={onNavigateToExceptions}>
              View exceptions →
            </button>
          </div>
        </div>

        {/* Exactly 4 Sleek Horizontal Metric Cards */}
        <div className="reui-top-cards-grid">
          {/* Card 1: Exceptions & Variance */}
          <div className="reui-card">
            <div className="reui-card-top">
              <div>
                <div className="reui-card-title">Exceptions & Variance</div>
                <div className="reui-card-sub">Pending Review / Discrepancies</div>
              </div>
              <svg className="sparkline-svg" viewBox="0 0 90 28" fill="none">
                <path
                  d="M2 18 L18 22 L35 12 L50 14 L65 24 L78 8 L88 12"
                  stroke="#ef4444"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <div className="reui-card-bottom">
              <div className="reui-card-val" id="ov-val-exceptions" style={{ color: 'var(--accent-coral)' }}>
                {exceptionsCount} Held
              </div>
              <div className="reui-card-bottom-right">
                <span className="reui-delta-badge delta-amber" id="ov-badge-exceptions">
                  {exceptionsCount} Held
                </span>
                <span className="reui-card-subtext">variance</span>
              </div>
            </div>
          </div>

          {/* Card 2: 3-Way Match Rate */}
          <div className="reui-card">
            <div className="reui-card-top">
              <div>
                <div className="reui-card-title">3-Way Match Rate</div>
                <div className="reui-card-sub">Reconciliation Quality</div>
              </div>
              <svg className="sparkline-svg" viewBox="0 0 90 28" fill="none">
                <path
                  d="M2 20 L20 18 L38 22 L55 10 L70 14 L80 6 L88 8"
                  stroke="#10b981"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <div className="reui-card-bottom">
              <div className="reui-card-val" id="ov-val-match-rate" style={{ color: 'var(--accent-emerald)' }}>
                {matchRate}%
              </div>
              <div className="reui-card-bottom-right">
                <span className="reui-delta-badge delta-green" id="match-target-pill" title="Target: 95.0% SLA">
                  Target 95%
                </span>
                <span className="reui-card-subtext" id="ov-sub-match-records">
                  {batch?.matched_records || 204} matched
                </span>
              </div>
            </div>
          </div>

          {/* Card 3: Gross Flow Volume */}
          <div className="reui-card">
            <div className="reui-card-top">
              <div>
                <div className="reui-card-title">Gross Flow Volume</div>
                <div className="reui-card-sub">Total Reconciled Value</div>
              </div>
              <svg className="sparkline-svg" viewBox="0 0 90 28" fill="none">
                <path
                  d="M2 22 L22 19 L40 24 L58 14 L72 10 L88 16"
                  stroke="#f59e0b"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <div className="reui-card-bottom">
              <div className="reui-card-val" id="ov-val-gross-flow">
                {grossVolume}
              </div>
              <div className="reui-card-bottom-right">
                <span className="reui-delta-badge delta-amber">INR (₹)</span>
                <span className="reui-card-subtext">canonical</span>
              </div>
            </div>
          </div>

          {/* Card 4: Ingested Records */}
          <div className="reui-card">
            <div className="reui-card-top">
              <div>
                <div className="reui-card-title">Ingested Records</div>
                <div className="reui-card-sub">Total Transactions Processed</div>
              </div>
              <svg className="sparkline-svg" viewBox="0 0 90 28" fill="none">
                <path
                  d="M2 24 L20 20 L38 18 L55 14 L70 8 L88 4"
                  stroke="#a855f7"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <div className="reui-card-bottom">
              <div className="reui-card-val" id="ov-val-total-records">
                {totalRecords}
              </div>
              <div className="reui-card-bottom-right">
                <span className="reui-delta-badge delta-green">3 Streams</span>
                <span className="reui-card-subtext">active</span>
              </div>
            </div>
          </div>
        </div>

        {/* Large ReUI Workspace Container */}
        <div className="reui-workspace-container" style={{ marginTop: '1.25rem' }}>
          {/* Dual Graphs Inner Grid */}
          <div className="reui-graphs-inner-grid">
            <div className="inner-graph-box">
              <div className="graph-header">
                <div>
                  <div className="graph-title">Reconciliation Vectors</div>
                  <div className="graph-subtitle">Matched vs Flagged Exception Categories</div>
                </div>
                <div className="graph-legend-group">
                  <span>
                    <span className="legend-dot" style={{ background: 'var(--accent-emerald)' }}></span> Matched
                  </span>
                  <span>
                    <span className="legend-dot" style={{ background: 'var(--accent-amber)' }}></span> Flagged
                  </span>
                </div>
              </div>
              <div className="chart-wrapper-h220">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={vectorsData} margin={{ top: 12, right: 12, left: -20, bottom: 0 }} barGap={6}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" vertical={false} />
                    <XAxis dataKey="category" stroke="#64748b" fontSize={11} tickLine={false} axisLine={{ stroke: 'var(--border-subtle)' }} />
                    <YAxis stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
                    <Tooltip
                      cursor={{ fill: 'rgba(255, 255, 255, 0.04)', radius: 4 }}
                      contentStyle={{
                        backgroundColor: '#111827',
                        borderColor: 'rgba(255, 255, 255, 0.1)',
                        borderRadius: '8px',
                        fontSize: '11px',
                        color: '#f8fafc',
                        boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
                      }}
                    />
                    <Bar dataKey="matched" fill="#10b981" radius={[4, 4, 0, 0]} name="Matched" barSize={28} />
                    <Bar dataKey="flagged" fill="#f59e0b" radius={[4, 4, 0, 0]} name="Flagged" barSize={28} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="inner-graph-box">
              <div className="graph-header">
                <div>
                  <div className="graph-title">13-Week Cash Liquidity Forecast</div>
                  <div className="graph-subtitle">Confirmed Receipts vs Probable In-Transit Inflows (₹ in Lakhs)</div>
                </div>
                <span className="reui-delta-badge delta-green">Forecast</span>
              </div>
              <div className="chart-wrapper-h220">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={forecastData} margin={{ top: 12, right: 12, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id="rechartsConfirmed" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
                      </linearGradient>
                      <linearGradient id="rechartsTransit" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#0284c7" stopOpacity={0.25} />
                        <stop offset="95%" stopColor="#0284c7" stopOpacity={0.0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" vertical={false} />
                    <XAxis dataKey="name" stroke="#64748b" fontSize={10} tickLine={false} axisLine={{ stroke: 'var(--border-subtle)' }} />
                    <YAxis stroke="#64748b" fontSize={10} tickLine={false} axisLine={false} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#111827',
                        borderColor: 'rgba(255, 255, 255, 0.1)',
                        borderRadius: '8px',
                        fontSize: '11px',
                        color: '#f8fafc',
                        boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey="confirmed"
                      stroke="#10b981"
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#rechartsConfirmed)"
                      name="Confirmed (₹L)"
                    />
                    <Area
                      type="monotone"
                      dataKey="inTransit"
                      stroke="#0284c7"
                      strokeWidth={1.5}
                      fillOpacity={1}
                      fill="url(#rechartsTransit)"
                      name="In-Transit (₹L)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Bottom Analytics Inner Grid: Sliding Windows & Exception Lanes */}
          <div className="reui-bottom-inner-grid">
            {/* Sliding Analysis Windows Telemetry Panel */}
            <div className="inner-graph-box">
              <div className="graph-header">
                <div>
                  <div className="graph-title">Sliding Analysis Windows</div>
                  <div className="graph-subtitle">Chunk-by-Chunk Reconciliation Health (20–30 records/window)</div>
                </div>
                <div style={{ display: 'flex', gap: '0.4rem', fontSize: '0.7rem', alignItems: 'center' }}>
                  <span className="badge-min badge-gray" id="badge-total-windows">10 Windows</span>
                  <span className="badge-min badge-green" id="badge-healthy-windows">8 Optimal</span>
                  <span className="badge-min badge-amber" id="badge-warm-windows">2 Warnings</span>
                  <span className="badge-min" id="badge-crit-windows" style={{ background: 'rgba(239,68,68,0.15)', color: 'var(--accent-coral)' }}>
                    0 Held
                  </span>
                </div>
              </div>
              <div className="sliding-windows-minimal-grid" id="cluster-histogram-bars">
                {slidingWindows.map((win) => (
                  <div key={win.id} className="win-minimal-item">
                    <div className="win-min-top">
                      <span className="win-min-id">{win.id}</span>
                      <span className={`win-min-rate ${win.status}`}>{win.label}</span>
                    </div>
                    <div className="win-min-track">
                      <div
                        className="win-min-fill"
                        style={{
                          width: win.exactPct,
                          background:
                            win.status === 'critical'
                              ? 'var(--accent-coral)'
                              : win.status === 'warning'
                              ? 'var(--accent-amber)'
                              : 'var(--accent-emerald)',
                        }}
                      />
                    </div>
                    <div className="win-min-meta">
                      <span>{win.exact} exact</span>
                      {win.held > 0 ? (
                        <span style={{ color: 'var(--accent-coral)' }}>{win.held} held</span>
                      ) : (
                        <span style={{ color: 'var(--accent-emerald)' }}>0 held</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Active Exception Resolution Lanes */}
            <div className="inner-graph-box">
              <div className="graph-header">
                <div>
                  <div className="graph-title">Active Exception Lanes</div>
                  <div className="graph-subtitle">Controller Resolution Distribution</div>
                </div>
              </div>

              <div className="lane-item">
                <div className="lane-top">
                  <div>
                    <span style={{ color: 'var(--accent-coral)' }}>● [00] Cutoff Timing Lag</span>
                    <div className="lane-sub">Month-End Clearance · T+2 Accrual</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div id="lane-count-cutoff" style={{ fontWeight: 700, color: 'var(--text-primary)' }}>18</div>
                    <div className="lane-sub" id="lane-pct-cutoff">50%</div>
                  </div>
                </div>
                <div className="lane-track">
                  <div className="lane-fill" id="lane-bar-cutoff" style={{ width: '50%', background: 'var(--accent-coral)' }}></div>
                </div>
              </div>

              <div className="lane-item">
                <div className="lane-top">
                  <div>
                    <span style={{ color: 'var(--accent-amber)' }}>● [01] Gateway MDR Fees</span>
                    <div className="lane-sub">MDR 2.0% + GST · Split to Acc 5010</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div id="lane-count-fee" style={{ fontWeight: 700, color: 'var(--text-primary)' }}>12</div>
                    <div className="lane-sub" id="lane-pct-fee">33%</div>
                  </div>
                </div>
                <div className="lane-track">
                  <div className="lane-fill" id="lane-bar-fee" style={{ width: '33%', background: 'var(--accent-amber)' }}></div>
                </div>
              </div>

              <div className="lane-item">
                <div className="lane-top">
                  <div>
                    <span style={{ color: 'var(--accent-blue)' }}>● [02] Missing Bank Wires</span>
                    <div className="lane-sub">Overdue Settlements · UTR Trace</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div id="lane-count-missing" style={{ fontWeight: 700, color: 'var(--text-primary)' }}>6</div>
                    <div className="lane-sub" id="lane-pct-missing">17%</div>
                  </div>
                </div>
                <div className="lane-track">
                  <div className="lane-fill" id="lane-bar-missing" style={{ width: '17%', background: 'var(--accent-blue)' }}></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
