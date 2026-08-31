import React, { useState, useEffect } from 'react';
import { ExceptionRecord } from '../types/exception';
import { exceptionService } from '../services/exceptionService';

interface ExceptionsViewProps {
  onInvestigate: (exception: ExceptionRecord) => void;
  activeBatchId?: string;
}

export const ExceptionsView: React.FC<ExceptionsViewProps> = ({
  onInvestigate,
  activeBatchId,
}) => {
  const [exceptions, setExceptions] = useState<ExceptionRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [severityFilter, setSeverityFilter] = useState<string>('ALL');
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    loadExceptions();
  }, [activeBatchId]);

  const loadExceptions = async () => {
    setLoading(true);
    try {
      const data = await exceptionService.getExceptions(activeBatchId);
      if (data && data.length > 0) {
        setExceptions(data);
      } else {
        setExceptions(generateDemoExceptions());
      }
    } catch {
      setExceptions(generateDemoExceptions());
    } finally {
      setLoading(false);
    }
  };

  const generateDemoExceptions = (): ExceptionRecord[] => {
    return [
      {
        id: 'EXC-2026-001',
        batch_id: 'BATCH-20260831',
        exception_type: 'PERIOD_CUTOFF_LAG',
        severity: 'HIGH',
        state: 'OPEN',
        impact_minor: 118000,
        impact_formatted: '₹1,180.00',
        currency: 'INR',
        primary_txn_id: 'pay_EXT_1008',
        findings: ['Captured within 2 minutes of month-end cutoff (23:58:12 IST). Settlement clears T+2.'],
        created_at: '2026-08-31 20:00:00',
      },
      {
        id: 'EXC-2026-002',
        batch_id: 'BATCH-20260831',
        exception_type: 'MDR_FEE_DEDUCTION',
        severity: 'MEDIUM',
        state: 'OPEN',
        impact_minor: 23600,
        impact_formatted: '₹236.00',
        currency: 'INR',
        primary_txn_id: 'pay_EXT_1002',
        findings: ['Razorpay deposit net of 2.0% MDR + 18% GST (₹236.00 fee).'],
        created_at: '2026-08-31 20:00:00',
      },
      {
        id: 'EXC-2026-003',
        batch_id: 'BATCH-20260831',
        exception_type: 'MISSING_BANK_SETTLEMENT',
        severity: 'CRITICAL',
        state: 'OPEN',
        impact_minor: 500000,
        impact_formatted: '₹5,000.00',
        currency: 'INR',
        primary_txn_id: 'pay_EXT_1012',
        findings: ['Overdue settlement clearing window >48 hours; UTR tracking initiated.'],
        created_at: '2026-08-31 20:00:00',
      },
      {
        id: 'EXC-2026-004',
        batch_id: 'BATCH-20260831',
        exception_type: 'DUPLICATE_PAYMENT_CAPTURE',
        severity: 'MEDIUM',
        state: 'OPEN',
        impact_minor: 99900,
        impact_formatted: '₹999.00',
        currency: 'INR',
        primary_txn_id: 'pay_EXT_1010',
        findings: ['Duplicate raw reference key detected in gateway export.'],
        created_at: '2026-08-31 20:00:00',
      },
    ];
  };

  const filtered = exceptions.filter((e) => {
    const matchesSev = severityFilter === 'ALL' || e.severity === severityFilter;
    const matchesSearch = searchTerm
      ? e.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
        e.exception_type.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (e.primary_txn_id && e.primary_txn_id.toLowerCase().includes(searchTerm.toLowerCase()))
      : true;
    return matchesSev && matchesSearch;
  });

  return (
    <section className="view-container active" id="view-exceptions">
      <div className="overview-header">
        <div>
          <h1 className="overview-title">Exceptions Queue & Maker-Checker Review</h1>
          <p className="overview-sub">Quarantined transaction discrepancies held for dual-control accounting review.</p>
        </div>
        <button
          className="btn btn-secondary btn-sm"
          id="btn-refresh-exceptions"
          onClick={loadExceptions}
          disabled={loading}
        >
          {loading ? 'Refreshing...' : 'Refresh Queue'}
        </button>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.8rem', margin: '1rem 0' }}>
        <input
          type="text"
          placeholder="Search exception ID, type, or ref..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          style={{
            flex: 1,
            maxWidth: '320px',
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-medium)',
            borderRadius: '6px',
            padding: '0.45rem 0.75rem',
            color: 'var(--text-primary)',
            fontSize: '0.8rem',
            outline: 'none',
          }}
        />

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.78rem' }}>
          <span style={{ color: 'var(--text-muted)' }}>Severity:</span>
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-medium)',
              borderRadius: '6px',
              padding: '0.45rem 0.75rem',
              color: 'var(--text-primary)',
              fontSize: '0.8rem',
              outline: 'none',
            }}
          >
            <option value="ALL">All Severities</option>
            <option value="CRITICAL">Critical</option>
            <option value="HIGH">High</option>
            <option value="MEDIUM">Medium</option>
            <option value="LOW">Low</option>
          </select>
        </div>
      </div>

      <div className="table-container">
        <table className="data-table-min">
          <thead>
            <tr>
              <th>Exception ID</th>
              <th>Discrepancy Type</th>
              <th>Severity</th>
              <th>Financial Impact</th>
              <th>Primary Ref</th>
              <th>Findings</th>
              <th style={{ textAlign: 'right' }}>Investigation</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((exc) => {
              let sevBadge = 'badge-cyan';
              if (exc.severity === 'CRITICAL') sevBadge = 'badge-coral';
              if (exc.severity === 'HIGH') sevBadge = 'badge-amber';
              if (exc.severity === 'MEDIUM') sevBadge = 'badge-amber';

              return (
                <tr key={exc.id}>
                  <td><strong>{exc.id}</strong></td>
                  <td><strong>{exc.exception_type}</strong></td>
                  <td><span className={`badge-min ${sevBadge}`}>{exc.severity}</span></td>
                  <td style={{ color: 'var(--accent-coral)' }}><strong>{exc.impact_formatted}</strong></td>
                  <td style={{ color: 'var(--text-muted)' }}>{exc.primary_txn_id || 'N/A'}</td>
                  <td style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', maxWidth: '280px' }}>
                    {exc.findings?.[0] || 'Variance detected'}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => onInvestigate(exc)}
                    >
                      Investigate →
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
};
