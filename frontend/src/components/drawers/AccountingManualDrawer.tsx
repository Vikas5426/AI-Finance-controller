import React from 'react';

interface AccountingManualDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

export const AccountingManualDrawer: React.FC<AccountingManualDrawerProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return (
    <div className="drawer-overlay active" id="drawer-manual" onClick={onClose}>
      <div className="drawer-content" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <div className="drawer-title">Accounting Knowledge Manual</div>
            <div className="drawer-sub">GAAP, ASC 606 & SOX-404 ITGC Control Standards</div>
          </div>
          <button className="btn-ghost btn-sm" onClick={onClose} style={{ border: 'none', fontSize: '1.1rem', cursor: 'pointer', color: 'var(--text-muted)' }}>
            ✕
          </button>
        </div>

        <div className="drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', overflowY: 'auto' }}>
          <div style={{ background: 'var(--bg-surface)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.4rem' }}>
              1. ASC 606 / Ind AS 115 Revenue Recognition
            </div>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.45 }}>
              Gross transaction amounts are recognized when performance obligation is fulfilled at capture. Processing fees are presented as operating expense (Debit 5010) rather than revenue reduction.
            </p>
          </div>

          <div style={{ background: 'var(--bg-surface)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.4rem' }}>
              2. SOX-404 Internal Controls over Financial Reporting
            </div>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.45, marginBottom: '0.4rem' }}>
              Segregation of duties enforces that no analyst (Maker) can approve or post their own proposed adjustment vouchers. All approvals require dual-control sign-off by a designated Controller (Checker).
            </p>
            <div style={{ fontSize: '0.72rem', color: 'var(--accent-emerald)' }}>✔ Automated dual-control authorization check active</div>
          </div>

          <div style={{ background: 'var(--bg-surface)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.4rem' }}>
              3. Cryptographic SHA-256 Ledger Immutability
            </div>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.45 }}>
              Each batch lifecycle event (Ingestion, Validation, Hungarian Matching, Exception Triage, Proposal Approval) produces a SHA-256 block cryptographically linked to the Genesis block, preventing unauthorized modifications.
            </p>
          </div>

          <div style={{ background: 'var(--bg-surface)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.4rem' }}>
              4. Materiality & Escalation Matrix
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              • <strong>Tier 1 (&lt; ₹500):</strong> Auto-remediated with deterministic math verification.<br />
              • <strong>Tier 2 (₹500 – ₹25,000):</strong> Analyst (Maker) proposal + Automated rule check.<br />
              • <strong>Tier 3 (₹25,000 – ₹1,00,000):</strong> Mandatory Controller (Checker) dual sign-off.<br />
              • <strong>Tier 4 (&gt; ₹1,00,000):</strong> Executive CFO / Treasury Director authorization.
            </div>
          </div>
        </div>

        <div className="drawer-footer">
          <button className="btn btn-secondary btn-sm" onClick={onClose} style={{ width: '100%' }}>
            Close Manual Viewer
          </button>
        </div>
      </div>
    </div>
  );
};
