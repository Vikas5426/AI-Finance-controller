export type ExceptionSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
export type ExceptionState = 'OPEN' | 'IN_REVIEW' | 'PROPOSED' | 'APPROVED' | 'REJECTED';

export interface ResolutionProposal {
  id: string;
  exception_id: string;
  action_type: 'ACCRUAL_ENTRY' | 'FEE_EXPENSE_RECOGNITION' | 'SUSPENSE_CLEARING' | 'UTR_TRACE_REQUEST';
  debit_account?: string;
  credit_account?: string;
  amount_minor: number;
  amount_formatted: string;
  confidence: number;
  reasoning: string;
  status: 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED';
  verified_by_gate: boolean;
  proposed_by: string;
  created_at: string;
}

export interface ExceptionRecord {
  id: string;
  batch_id: string;
  exception_type: string;
  severity: ExceptionSeverity;
  state: ExceptionState;
  impact_minor: number;
  impact_formatted: string;
  currency: string;
  primary_txn_id?: string;
  counterpart_txn_id?: string;
  findings?: string[];
  proposal?: ResolutionProposal;
  created_at: string;
}
