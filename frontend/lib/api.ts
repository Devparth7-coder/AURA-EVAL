/**
 * Typed API client. The base URL always comes from the environment (§37) —
 * never a hardcoded host. When NEXT_PUBLIC_API_URL is empty the app uses
 * relative URLs served by the Next.js rewrite proxy.
 */
import type {
  AnalyticsCharts, AnalyticsSummary, CostReport, Dataset, EvaluationAnalytics,
  Experiment, PromptTemplate, Project, ReliabilityReport, Run, RunGraph,
  RunStatusPayload, SOP, Sample, Workflow, WorkflowEvent,
} from './types';

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || '').replace(/\/$/, '');

export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public retryable = false,
  ) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
      cache: 'no-store',
    });
  } catch {
    throw new ApiError('NETWORK_ERROR', 'Cannot reach the AURA-EVAL API.', 0, true);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new ApiError(
      body?.error || 'REQUEST_FAILED',
      body?.message || `Request failed with ${res.status}`,
      res.status,
      Boolean(body?.retryable),
    );
  }
  return body as T;
}

const get = <T,>(p: string) => request<T>(p);
const post = <T,>(p: string, body?: unknown) =>
  request<T>(p, { method: 'POST', body: JSON.stringify(body ?? {}) });
const put = <T,>(p: string, body: unknown) =>
  request<T>(p, { method: 'PUT', body: JSON.stringify(body) });
const del = (p: string) => request<void>(p, { method: 'DELETE' });

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const s = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') s.set(k, String(v)); });
  const out = s.toString();
  return out ? `?${out}` : '';
};

export const api = {
  health: () => get<{ status: string; database: string; llm: string; environment: string }>('/api/health'),
  healthLlm: () => get<{ status: string; active_provider: string; active_model: string; providers: Record<string, string>; demo_mode: boolean }>('/api/health/llm'),
  config: () => get<Record<string, unknown>>('/api/health/config'),

  projects: () => get<Project[]>('/api/projects'),
  createProject: (b: { name: string; description?: string; tags?: string[] }) => post<Project>('/api/projects', b),
  deleteProject: (id: string) => del(`/api/projects/${id}`),

  sops: (projectId?: string) => get<SOP[]>(`/api/sops${qs({ project_id: projectId })}`),
  sop: (id: string) => get<SOP>(`/api/sops/${id}`),
  sopDefaults: () => get<{ rules: any[]; scoring: any; threshold: number }>('/api/sops/defaults'),
  createSop: (b: unknown) => post<SOP>('/api/sops', b),
  updateSop: (id: string, b: unknown) => put<SOP>(`/api/sops/${id}`, b),
  deleteSop: (id: string) => del(`/api/sops/${id}`),
  activateSop: (id: string, active: boolean) => post<SOP>(`/api/sops/${id}/activate${qs({ active })}`),
  restoreSopVersion: (id: string, v: number) => post<SOP>(`/api/sops/${id}/versions/${v}/restore`),
  renderSop: (id: string) => get<{ text: string }>(`/api/sops/${id}/render`),
  testSop: (id: string, samples: Record<string, unknown>[]) =>
    post<{ sop: string; version: number; results: any[] }>(`/api/sops/${id}/test`, { samples }),

  workflows: (projectId?: string) => get<Workflow[]>(`/api/workflows${qs({ project_id: projectId })}`),
  workflow: (id: string) => get<Workflow>(`/api/workflows/${id}`),
  createWorkflow: (b: unknown) => post<Workflow>('/api/workflows', b),
  updateWorkflow: (id: string, b: unknown) => put<Workflow>(`/api/workflows/${id}`, b),
  deleteWorkflow: (id: string) => del(`/api/workflows/${id}`),
  topology: () => get<{ nodes: any[]; edges: any[] }>('/api/workflows/topology'),
  runWorkflow: (id: string, b?: { sample_count?: number; async_execution?: boolean }) =>
    post<Run>(`/api/workflows/${id}/run`, b ?? {}),
  workflowRuns: (id: string) => get<Run[]>(`/api/workflows/${id}/runs`),

  runs: (status?: string) => get<Run[]>(`/api/runs${qs({ status })}`),
  run: (id: string) => get<Run>(`/api/runs/${id}`),
  runStatus: (id: string) => get<RunStatusPayload>(`/api/runs/${id}/status`),
  runEvents: (id: string, afterSeq = 0) => get<WorkflowEvent[]>(`/api/runs/${id}/events${qs({ after_seq: afterSeq })}`),
  runTrace: (id: string) => get<import('./types').AgentRunTrace[]>(`/api/runs/${id}/trace`),
  runGraph: (id: string) => get<RunGraph>(`/api/runs/${id}/graph`),
  advanceRun: (id: string, maxSteps = 40) => post<Run>(`/api/runs/${id}/advance`, { max_steps: maxSteps }),
  stopRun: (id: string) => post<Run>(`/api/runs/${id}/stop`),

  samples: (params: { run_id?: string; status?: string; min_score?: number; limit?: number } = {}) =>
    get<Sample[]>(`/api/samples${qs(params)}`),
  sample: (id: string) => get<Sample>(`/api/samples/${id}`),
  sampleHistory: (id: string) => get<{ sample_id: string; sample_key: string; status: string;
    retry_count: number; final_score: number | null; timeline: any[] }>(`/api/samples/${id}/history`),
  reviewQueue: (runId?: string) => get<Sample[]>(`/api/samples/review-queue${qs({ run_id: runId })}`),
  approveSample: (id: string, b: { reviewer?: string; feedback?: string }) => post<Sample>(`/api/samples/${id}/approve`, b),
  rejectSample: (id: string, b: { reviewer?: string; feedback?: string }) => post<Sample>(`/api/samples/${id}/reject`, b),
  editSample: (id: string, b: { reviewer?: string; feedback?: string; edited_payload: Record<string, unknown> }) =>
    post<Sample>(`/api/samples/${id}/edit`, b),

  datasets: (params: { run_id?: string; project_id?: string } = {}) => get<Dataset[]>(`/api/datasets${qs(params)}`),
  dataset: (id: string) => get<Dataset>(`/api/datasets/${id}`),
  datasetPreview: (id: string, limit = 20) => get<{ name: string; style: string; row_count: number; rows: any[] }>(`/api/datasets/${id}/preview${qs({ limit })}`),
  createDataset: (b: { run_id: string; style: string; formats: string[]; name?: string }) => post<Dataset>('/api/datasets', b),
  downloadUrl: (id: string, format: string) => apiUrl(`/api/datasets/${id}/download?format=${format}`),

  analytics: (runId?: string) => get<{ summary: AnalyticsSummary; charts: AnalyticsCharts }>(`/api/analytics${qs({ run_id: runId })}`),
  evaluationAnalytics: (runId?: string) => get<EvaluationAnalytics>(`/api/analytics/evaluation${qs({ run_id: runId })}`),
  reliability: (runId?: string) => get<ReliabilityReport>(`/api/analytics/reliability${qs({ run_id: runId })}`),
  cost: (runId?: string) => get<CostReport>(`/api/analytics/cost${qs({ run_id: runId })}`),

  experiments: () => get<Experiment[]>('/api/experiments'),
  experiment: (id: string) => get<Experiment>(`/api/experiments/${id}`),
  createExperiment: (b: unknown) => post<Experiment>('/api/experiments', b),

  prompts: () => get<PromptTemplate[]>('/api/prompts'),
  addPromptVersion: (id: string, b: { body: string; notes?: string }) => post<PromptTemplate>(`/api/prompts/${id}/versions`, b),
  promptDiff: (id: string, a: number, b: number) => get<{ diff: string[] }>(`/api/prompts/${id}/diff${qs({ a, b })}`),
};
