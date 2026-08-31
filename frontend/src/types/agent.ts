export interface ThoughtStep {
  step_number: number;
  label: string;
  thought: string;
  action_type?: string;
  status: 'running' | 'completed' | 'verified';
  duration_ms: number;
}

export interface AgentTelemetry {
  agent_id: string;
  name: string;
  role: string;
  llm_engine: string;
  execution_time_ms: number;
  token_usage_estimated: number;
  deterministic_gate_passed: boolean;
  confidence_score: number;
}

export interface AgentRunResponse {
  agent_id: string;
  batch_id: string;
  status: 'SUCCESS' | 'FAILED';
  executive_markdown: string;
  structured_json: Record<string, any>;
  telemetry: AgentTelemetry;
  thought_stream: ThoughtStep[];
}
