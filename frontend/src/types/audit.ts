export interface AuditEvent {
  id: string;
  batch_id: string;
  event_seq: number;
  event_type: string;
  entity_type: string;
  entity_id: string;
  actor_id: string;
  actor_type: string;
  action: string;
  prev_hash: string;
  event_hash: string;
  created_at: string;
  metadata?: Record<string, any>;
}

export interface AuditChainVerification {
  is_valid: boolean;
  total_blocks: number;
  genesis_hash: string;
  latest_hash: string;
  tamper_detected: boolean;
  broken_block_seq?: number;
  verified_at: string;
}
