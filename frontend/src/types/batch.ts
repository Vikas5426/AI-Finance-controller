export type BatchStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';

export interface SlidingWindowTelemetry {
  window_index: number;
  total_in_window: number;
  matched_in_window: number;
  match_rate: number;
  status: 'OPTIMAL' | 'WARNING' | 'CRITICAL';
}

export interface CashForecastWeek {
  week: number;
  label: string;
  confirmed_lakhs: number;
  in_transit_lakhs: number;
  total_lakhs: number;
  forecast_date: string;
}

export interface QualityMetrics {
  precision: number;
  recall: number;
  f1_score: number;
  accuracy: number;
}

export interface BatchSummary {
  total_records: number;
  matched_records: number;
  unmatched_records: number;
  exceptions_count: number;
  match_rate: number;
  exact_matches: number;
  contextual_matches: number;
  processing_time_ms?: number;
  quality_metrics?: QualityMetrics;
}

export interface DAGNodeState {
  id: string;
  label: string;
  sublabel: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  duration_ms?: number;
  icon?: string;
  metric?: string;
}

export interface ActiveBatchResponse {
  batch_id: string;
  status: BatchStatus;
  total_records: number;
  matched_records: number;
  match_rate: number;
  exact_matches: number;
  contextual_matches: number;
  exceptions_count: number;
  execution_time_sec?: number;
  summary?: BatchSummary;
  windows?: SlidingWindowTelemetry[];
  cash_forecast?: CashForecastWeek[];
  stats?: {
    gross_flow_formatted: string;
    unresolved_exceptions_formatted: string;
    settled_volume_formatted: string;
  };
}
