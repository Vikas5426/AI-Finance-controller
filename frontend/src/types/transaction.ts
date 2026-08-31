export type SourceKind = 'GATEWAY' | 'BANK' | 'LEDGER';

export type MatchStatus =
  | 'MATCHED'
  | 'MATCHED_EXACT'
  | 'MATCHED_CONTEXTUAL'
  | 'MATCHED_SETTLEMENT'
  | 'CUTOFF_LAG'
  | 'MDR_FEE'
  | 'MISSING_WIRE'
  | 'UNMATCHED'
  | 'UNRESOLVED_EXCEPTION';

export interface CanonicalTransaction {
  id: string;
  batch_id?: string;
  source_kind: SourceKind;
  raw_reference: string;
  amount_minor: number;
  amount_formatted: string;
  currency: string;
  transaction_date: string;
  direction: 'DEBIT' | 'CREDIT';
  status: MatchStatus;
  confidence_score?: number;
  matched_with_id?: string;
  metadata?: Record<string, any>;
}

export interface MatchedPair {
  id: string;
  primary_id: string;
  counterpart_id: string;
  match_tier: 'P0_EXACT' | 'P1_TIMING' | 'P2_REVERSAL' | 'P3_MDR_FEE' | 'P4_CONTEXTUAL';
  confidence: number;
  residual_paise: number;
  sop_code: string;
  settled_at: string;
}

export interface DeepWhyExplanation {
  category: MatchStatus;
  title: string;
  sop_code: string;
  sop_title: string;
  reason: string;
  applied_rules: string;
  matched_fields: string;
  variance: string;
  action_summary: string;
}
