export type RunStatus = 'PENDING' | 'RUNNING' | 'PAUSED' | 'COMPLETED' | 'FAILED' | 'STOPPED';

export interface Project {
  id: string; name: string; description: string; tags: string[];
  created_at: string; updated_at: string;
}

export interface SOPRule {
  id: string; text: string; criterion: string; weight: number;
  severity: 'minor' | 'major' | 'critical';
}

export interface SOPVersion {
  id: string; version: number; rules: SOPRule[]; scoring: Record<string, unknown>;
  threshold: number; changelog: string; created_at: string;
}

export interface SOP {
  id: string; project_id: string | null; name: string; description: string;
  is_active: boolean; current_version: number; versions: SOPVersion[];
  created_at: string; updated_at: string;
}

export interface WorkflowConfig {
  sample_count: number; batch_size: number; max_retries: number;
  provider: string; model: string; temperature: number; use_planner: boolean;
  judges: number; judge_models: string[]; approval_threshold: number;
  borderline_low: number; borderline_high: number; human_review_enabled: boolean;
  dataset_style: 'instruction' | 'chat' | 'evaluation';
  dataset_formats: string[]; domain_hint: string; max_cost_usd: number;
  mock_failure_rate: number;
}

export interface Workflow {
  id: string; project_id: string; sop_id: string | null; name: string;
  objective: string; config: Partial<WorkflowConfig>; is_archived: boolean;
  created_at: string; updated_at: string;
}

export interface Run {
  id: string; workflow_id: string; status: RunStatus; steps_executed: number;
  samples_generated: number; samples_approved: number; samples_rejected: number;
  samples_failed: number; samples_review: number;
  total_input_tokens: number; total_output_tokens: number; total_cost_usd: number;
  plan: Record<string, unknown>; error: Record<string, unknown> | null;
  started_at: string | null; finished_at: string | null; created_at: string;
}

export interface RunStatusPayload {
  run_id: string; status: RunStatus; resume_at: string | null;
  steps_executed: number; queue_remaining: number; samples_generated: number;
  samples_approved: number; samples_rejected: number; samples_review: number;
  samples_failed: number; cost_usd: number; tokens: number;
  last_event_seq: number; error: Record<string, unknown> | null; terminal: boolean;
}

export interface WorkflowEvent {
  id?: string; seq: number; type: string; level: string; message: string;
  data: Record<string, any>; created_at: string;
}

export interface AgentRunTrace {
  id: string; run_id: string; sample_id: string | null; agent: string;
  status: string; attempt: number; provider: string; model: string;
  prompt_key: string; prompt_version: number;
  input_json: Record<string, any>; output_json: Record<string, any>;
  latency_ms: number; input_tokens: number; output_tokens: number;
  cost_usd: number; error_type: string | null; error_message: string | null;
  created_at: string;
}

export interface Evaluation {
  id: string; sample_id: string; attempt: number; judge_label: string;
  approved: boolean; scores: Record<string, number>; overall_score: number;
  issues: { criterion: string; severity: string; detail: string }[];
  reasoning_summary: string; confidence: number; hallucination_risk: string;
  is_consensus: boolean; variance: number; agreement_rate: number;
  latency_ms: number; created_at: string;
}

export interface SampleVersion {
  id: string; version: number; payload: Record<string, any>; source: string;
  feedback_applied: string; outcome: string; created_at: string;
}

export interface Sample {
  id: string; run_id: string; sample_key: string; payload: Record<string, any>;
  status: string; retry_count: number; final_score: number | null;
  approval_report: Record<string, any>; failure_reason: string | null;
  created_at: string;
  versions?: SampleVersion[]; evaluations?: Evaluation[];
  reviews?: { id: string; reviewer: string; decision: string; feedback: string; created_at: string }[];
}

export interface Dataset {
  id: string; project_id: string | null; run_id: string | null; name: string;
  style: string; row_count: number; current_version: number;
  dataset_metadata: Record<string, any>; created_at: string;
  versions: { id: string; version: number; fmt: string; row_count: number;
    size_bytes: number; checksum: string; storage_key: string; created_at: string }[];
}

export interface AnalyticsSummary {
  total_workflows: number; total_runs: number; running: number; completed: number;
  failed: number; stopped: number; samples_generated: number; samples_approved: number;
  samples_rejected: number; samples_needs_review: number; samples_failed: number;
  avg_quality_score: number; median_quality_score: number;
  avg_evaluation_latency_ms: number; avg_retry_count: number;
  total_tokens: number; total_input_tokens: number; total_output_tokens: number;
  total_cost_usd: number; avg_cost_per_sample: number; datasets: number;
}

export interface AnalyticsCharts {
  score_distribution: { bucket: string; count: number }[];
  pass_fail: { name: string; value: number }[];
  agent_execution_time: { agent: string; avg_ms: number; p95_ms: number; calls: number }[];
  token_usage: { agent: string; input_tokens: number; output_tokens: number }[];
  cost_by_agent: { agent: string; cost_usd: number }[];
  scores_over_time: { index: number; score: number; approved: boolean; attempt: number; ts: string }[];
}

export interface EvaluationAnalytics {
  pass_rate: number; failure_rate: number; average_score: number; median_score: number;
  stdev_score: number; score_distribution: { bucket: string; count: number }[];
  average_retry_count: number; refinement_attempts: number; refinement_success_rate: number;
  hallucination_rate: number; schema_failure_rate: number; judge_disagreement_rate: number;
  criteria_pass_rates: Record<string, number>;
  top_failure_criteria: { criterion: string; failures: number; severity_breakdown: Record<string, number> }[];
  human_review_pending: number;
}

export interface ReliabilityReport {
  workflow_reliability: number;
  agents: { agent: string; calls: number; success: number; degraded: number; failed: number; reliability: number }[];
  error_breakdown: { error: string; count: number }[];
  retry_frequency: number; invalid_json_errors: number; schema_violations: number;
  timeouts: number; provider_errors: number; interrupted_runs: number; loop_guard_trips: number;
  failure_propagation: { run_id: string; status: string; chain: string[] }[];
}

export interface CostReport {
  total_cost_usd: number; input_tokens: number; output_tokens: number; total_tokens: number;
  avg_cost_per_sample: number;
  by_model: { model: string; input_tokens: number; output_tokens: number; cost_usd: number; calls: number }[];
}

export interface GraphNode { id: string; label: string; description: string }
export interface GraphEdge { source: string; target: string; label: string }
export interface NodeStats {
  calls: number; latency_ms: number; avg_latency_ms: number; tokens: number;
  cost_usd: number; errors: number; model: string; provider: string;
  prompt_key: string; prompt_version: number;
  last_output: Record<string, any>; last_input: Record<string, any>; status: string;
}
export interface RunGraph {
  nodes: GraphNode[]; edges: GraphEdge[]; stats: Record<string, NodeStats>;
  active_node: string | null; run_status: RunStatus;
}

export interface Experiment {
  id: string; name: string; description: string; status: string;
  config: Record<string, any>;
  report: {
    arms: { label: string; provider: string; model: string; prompt_version: number;
      run_id: string | null; metrics: Record<string, number> }[];
    comparison: { metric: string; label: string; unit: string;
      values: Record<string, number>; winner: string }[];
    wins: Record<string, number>; winner: string | null;
  };
  created_at: string;
}

export interface PromptTemplate {
  id: string; key: string; agent: string; description: string; current_version: number;
  versions: { id: string; version: number; body: string; notes: string; is_active: boolean; created_at: string }[];
}
