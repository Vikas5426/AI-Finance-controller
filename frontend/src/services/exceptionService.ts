import api from './api';
import { ExceptionRecord, ResolutionProposal } from '../types/exception';

export const exceptionService = {
  getExceptions: async (batchId?: string, limit = 100): Promise<ExceptionRecord[]> => {
    const params = new URLSearchParams();
    if (batchId) params.append('batch_id', batchId);
    params.append('limit', String(limit));
    const res = await api.get<any>(`/exceptions/?${params.toString()}`);
    return Array.isArray(res.data) ? res.data : res.data.items || [];
  },

  getPendingApprovals: async (batchId?: string): Promise<ResolutionProposal[]> => {
    const params = new URLSearchParams();
    if (batchId) params.append('batch_id', batchId);
    const res = await api.get<any>(`/approvals/pending?${params.toString()}`);
    return Array.isArray(res.data) ? res.data : res.data.items || [];
  },

  decideProposal: async (proposalId: string, decision: 'APPROVED' | 'REJECTED', notes?: string) => {
    const res = await api.post('/approvals/decide', {
      proposal_id: proposalId,
      decision,
      notes: notes || 'Reviewed via Maker-Checker UI',
    });
    return res.data;
  },

  investigateExceptionWithAgent9: async (exceptionId: string, payload?: Record<string, any>) => {
    const res = await api.post('/agents/investigate', {
      exception_id: exceptionId,
      ...payload,
    });
    return res.data;
  },
};
