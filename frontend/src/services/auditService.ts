import api from './api';
import { AuditEvent, AuditChainVerification } from '../types/audit';

export const auditService = {
  getAuditEvents: async (batchId?: string, limit = 100): Promise<AuditEvent[]> => {
    const params = new URLSearchParams();
    if (batchId) params.append('batch_id', batchId);
    params.append('limit', String(limit));
    const res = await api.get<any>(`/audit/events?${params.toString()}`);
    return Array.isArray(res.data) ? res.data : res.data.events || [];
  },

  verifyChain: async (): Promise<AuditChainVerification> => {
    const res = await api.get<AuditChainVerification>('/audit/verify-chain');
    return res.data;
  },

  explainWithAgent12: async () => {
    const res = await api.post('/agents/run', {
      agent_id: 'agent_12_audit_trail',
      payload: { action: 'EXPLAIN_CHAIN_INTEGRITY' },
    });
    return res.data;
  },
};
