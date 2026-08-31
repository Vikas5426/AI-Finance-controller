import React from 'react';

interface SOPRulesDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SOPRulesDrawer: React.FC<SOPRulesDrawerProps> = ({ isOpen, onClose }) => {
  const sopRules = [
    {
      id: 'SOP-01',
      name: 'Deterministic Exact 1:1 Matching',
      tier: 'P0 Priority',
      status: 'Active · Auto-Commit',
      condition: '1:1 reference key match (Invoice ID, Payment ID, UTR) with 0-paise residual.',
      action: 'Automatically seal in SHA-256 block ledger. Post to Account 1200.',
      tolerance: '₹0.00 Tolerance',
    },
    {
      id: 'SOP-02',
      name: 'Period Cutoff Timing Boundary SLA',
      tier: 'P1 Priority',
      status: 'Active · T+2 SLA',
      condition: 'Captures within 15 mins of month boundary where bank deposit clears T+2.',
      action: 'Post accrual journal voucher to Account 1290 (Cash In-Transit).',
      tolerance: 'T+2 Clearing Window',
    },
    {
      id: 'SOP-03',
      name: 'Reversal & Chargeback Netting',
      tier: 'P2 Priority',
      status: 'Active · Netting Engine',
      condition: 'Refund or chargeback debit linked to original settlement capture.',
      action: 'Offset contra-revenue account and reverse original MDR processing fee.',
      tolerance: 'Full & Partial Netting',
    },
    {
      id: 'SOP-04',
      name: 'Gateway MDR Fee & GST Netting',
      tier: 'P3 Priority',
      status: 'Active · 1-Paise Verified',
      condition: 'Bank credit deposited net of 2.0% MDR + 18% GST (Calculated residual matches).',
      action: 'Debit Account 5010 (Gateway Processing Fees) per ASC 606.',
      tolerance: 'MDR Formula Checked',
    },
    {
      id: 'SOP-05',
      name: 'Missing Settlement & UTR Tracing',
      tier: 'P4 Priority',
      status: 'Active · Maker-Checker',
      condition: 'Gateway capture exceeding 48-hour SLA without matching bank statement deposit.',
      action: 'Hold in dual-control review queue; dispatch automated bank UTR trace.',
      tolerance: '>48 Hours SLA Threshold',
    },
  ];

  if (!isOpen) return null;

  return (
    <div className="drawer-overlay active" id="drawer-sop" onClick={onClose}>
      <div className="drawer-content" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <div className="drawer-title">SOP Rules Engine</div>
            <div className="drawer-sub">Autonomous standard operating policies</div>
          </div>
          <button className="btn-ghost btn-sm" onClick={onClose} style={{ border: 'none', fontSize: '1.1rem', cursor: 'pointer', color: 'var(--text-muted)' }}>
            ✕
          </button>
        </div>

        <div className="drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem', overflowY: 'auto' }}>
          {sopRules.map((rule) => (
            <div
              key={rule.id}
              style={{
                background: 'var(--bg-surface)',
                padding: '1rem',
                borderRadius: '8px',
                border: '1px solid var(--border-subtle)',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.5rem',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--accent-cyan)' }}>
                  {rule.id} · {rule.name}
                </span>
                <span className="badge-min badge-gray" style={{ fontSize: '0.65rem' }}>{rule.tier}</span>
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                <strong>Condition:</strong> {rule.condition}
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--accent-emerald)' }}>
                <strong>Action:</strong> {rule.action}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-dim)', borderTop: '1px solid var(--border-subtle)', paddingTop: '0.4rem' }}>
                <span>Tolerance: {rule.tolerance}</span>
                <span style={{ color: 'var(--accent-emerald)' }}>● {rule.status}</span>
              </div>
            </div>
          ))}
        </div>

        <div className="drawer-footer">
          <button className="btn btn-secondary btn-sm" onClick={onClose} style={{ width: '100%' }}>
            Close Rules Viewer
          </button>
        </div>
      </div>
    </div>
  );
};
