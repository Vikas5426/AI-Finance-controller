import api from './api';
import { ActiveBatchResponse } from '../types/batch';
import { CanonicalTransaction } from '../types/transaction';

export const batchService = {
  getLatestBatch: async (): Promise<ActiveBatchResponse | null> => {
    try {
      const res = await api.get<ActiveBatchResponse>('/batches/latest');
      return res.data;
    } catch {
      try {
        const res = await api.get<ActiveBatchResponse>('/batches/active');
        return res.data;
      } catch {
        return null;
      }
    }
  },

  runBatch: async (params?: {
    record_count?: number;
    window_size?: number;
    upload_ids?: string[];
  }): Promise<ActiveBatchResponse> => {
    const res = await api.post<ActiveBatchResponse>('/batches/run', params || { record_count: 240, window_size: 24 });
    return res.data;
  },

  uploadFeeds: async (formData: FormData): Promise<ActiveBatchResponse> => {
    try {
      const uploadRes = await api.post('/sources/upload-batch', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      const uploadIds = (uploadRes.data.items || []).map((item: any) => item.upload_id);
      if (uploadIds.length > 0) {
        const runRes = await api.post<ActiveBatchResponse>('/batches/run', {
          upload_ids: uploadIds,
          record_count: 240,
          window_size: 24,
        });
        return runRes.data;
      }
    } catch (e) {
      console.warn('Backend file upload fallback to standard run:', e);
    }
    return batchService.runBatch({ record_count: 240, window_size: 24 });
  },

  getTransactions: async (batchId?: string, limit = 200): Promise<CanonicalTransaction[]> => {
    const params = new URLSearchParams();
    if (batchId) params.append('batch_id', batchId);
    params.append('limit', String(limit));
    const res = await api.get<any>(`/transactions/?${params.toString()}`);
    return Array.isArray(res.data) ? res.data : res.data.items || [];
  },
};

export type { ActiveBatchResponse };
