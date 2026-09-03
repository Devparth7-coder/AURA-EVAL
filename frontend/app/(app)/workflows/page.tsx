'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import { Play, Plus, Trash2 } from 'lucide-react';
import { PageHeader } from '@/components/Shell';
import { Empty, ErrorState, Field, Modal, Panel, Spinner, StatusChip } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api, ApiError } from '@/lib/api';
import { fmt } from '@/lib/utils';
import type { Run } from '@/lib/types';

const DEFAULT_CONFIG = {
  sample_count: 8, batch_size: 4, max_retries: 3, provider: 'mock', model: 'mock-1',
  temperature: 0.4, use_planner: true, judges: 3, judge_models: [] as string[],
  approval_threshold: 75, borderline_low: 60, borderline_high: 75,
  human_review_enabled: true, dataset_style: 'instruction' as const,
  dataset_formats: ['jsonl', 'json', 'csv'], domain_hint: 'python coding',
  max_cost_usd: 25, mock_failure_rate: 0.06,
};

export default function WorkflowsPage() {
  const router = useRouter();
  const workflows = useAsync(() => api.workflows(), [], { poll: 8000 });
  const projects = useAsync(() => api.projects(), []);
  const sops = useAsync(() => api.sops(), []);
  const runs = useAsync(() => api.runs(), [], { poll: 5000 });

  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: '', objective: '', project_id: '', sop_id: '', config: DEFAULT_CONFIG,
  });

  const latestRun = useMemo(() => {
    const map: Record<string, Run | undefined> = {};
    (runs.data || []).forEach((r) => { if (!map[r.workflow_id]) map[r.workflow_id] = r; });
    return map;
  }, [runs.data]);

  async function create() {
    setError(null);
    setBusy('create');
    try {
      const projectId = form.project_id || projects.data?.[0]?.id;
      if (!projectId) throw new ApiError('NO_PROJECT', 'Create a project first.', 400);
      const wf = await api.createWorkflow({
        project_id: projectId,
        name: form.name || 'Untitled workflow',
        objective: form.objective,
        sop_id: form.sop_id || null,
        config: form.config,
      });
      setOpen(false);
      router.push(`/workflows/${wf.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(null); }
  }

  async function start(id: string) {
    setBusy(id);
    setError(null);
    try {
      const run = await api.runWorkflow(id, { async_execution: true });
      router.push(`/runs/${run.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(null); }
  }

  async function remove(id: string) {
    setBusy(id);
    try { await api.deleteWorkflow(id); await workflows.refresh(true); }
    finally { setBusy(null); }
  }

  if (workflows.loading && !workflows.data) return <Spinner label="Loading workflows…" />;
  if (workflows.error) return <ErrorState error={workflows.error} onRetry={() => workflows.refresh()} />;

  const list = workflows.data || [];

  return (
    <>
      <PageHeader title="Workflows"
        description="Configured agent pipelines. Each run executes planner → generator → critic → refiner → approval → dataset builder."
        actions={<button onClick={() => setOpen(true)} className="btn-primary btn-sm"><Plus className="h-3.5 w-3.5" /> New workflow</button>} />

      {error && <div className="mb-4 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{error}</div>}

      {list.length === 0 ? (
        <Panel><Empty title="No workflows yet" hint="Create a workflow to define an objective, an SOP and the agent configuration."
          action={<button onClick={() => setOpen(true)} className="btn-primary btn-sm">Create workflow</button>} /></Panel>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {list.map((w) => {
            const run = latestRun[w.id];
            const cfg = w.config || {};
            return (
              <div key={w.id} className="panel flex flex-col p-4 transition-colors hover:border-slate-700">
                <div className="flex items-start justify-between gap-2">
                  <Link href={`/workflows/${w.id}`} className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-slate-100 hover:text-accent-soft">{w.name}</h3>
                    <p className="mt-1 line-clamp-2 text-xs text-slate-500">{w.objective || 'No objective set'}</p>
                  </Link>
                  {run && <StatusChip status={run.status} />}
                </div>

                <div className="mt-3 grid grid-cols-3 gap-2 text-2xs">
                  {[
                    ['samples', cfg.sample_count ?? '—'],
                    ['judges', cfg.judges ?? 1],
                    ['retries', cfg.max_retries ?? 3],
                    ['model', cfg.model ?? 'mock-1'],
                    ['style', cfg.dataset_style ?? 'instruction'],
                    ['threshold', cfg.approval_threshold ?? 75],
                  ].map(([k, v]) => (
                    <div key={String(k)} className="rounded-md border border-line bg-base-850/60 px-2 py-1.5">
                      <div className="text-slate-600">{k}</div>
                      <div className="mono truncate text-slate-300">{String(v)}</div>
                    </div>
                  ))}
                </div>

                {run && (
                  <div className="mt-3 flex flex-wrap gap-3 border-t border-line pt-3 text-2xs text-slate-500">
                    <span>{run.samples_generated} generated</span>
                    <span className="text-ok">{run.samples_approved} approved</span>
                    <span className="text-danger">{run.samples_rejected} rejected</span>
                    <span>{fmt.usd(run.total_cost_usd)}</span>
                    <span>{fmt.ago(run.created_at)}</span>
                  </div>
                )}

                <div className="mt-4 flex items-center gap-2">
                  <button onClick={() => start(w.id)} disabled={busy === w.id} className="btn-primary btn-sm flex-1">
                    <Play className="h-3.5 w-3.5" /> {busy === w.id ? 'Starting…' : 'Run'}
                  </button>
                  <Link href={`/workflows/${w.id}`} className="btn-ghost btn-sm">Inspect</Link>
                  <button onClick={() => remove(w.id)} className="btn-ghost btn-sm px-2" title="Delete">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="Create workflow" wide>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name"><input className="input" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Python Assistant Dataset v2" /></Field>
          <Field label="Project">
            <select className="input" value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value })}>
              <option value="">{projects.data?.[0]?.name ?? 'Default project'}</option>
              {(projects.data || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Field>
          <div className="sm:col-span-2">
            <Field label="Objective" hint="The planner decomposes this into subtasks and dataset fields.">
              <textarea className="input h-20 resize-y" value={form.objective}
                onChange={(e) => setForm({ ...form, objective: e.target.value })}
                placeholder="Create a dataset for evaluating Python coding assistants" />
            </Field>
          </div>
          <Field label="SOP">
            <select className="input" value={form.sop_id} onChange={(e) => setForm({ ...form, sop_id: e.target.value })}>
              <option value="">Default built-in SOP</option>
              {(sops.data || []).map((s) => <option key={s.id} value={s.id}>{s.name} (v{s.current_version})</option>)}
            </select>
          </Field>
          <Field label="Domain hint"><input className="input" value={form.config.domain_hint}
            onChange={(e) => setForm({ ...form, config: { ...form.config, domain_hint: e.target.value } })} /></Field>

          <Field label="Sample count"><input type="number" min={1} max={200} className="input"
            value={form.config.sample_count}
            onChange={(e) => setForm({ ...form, config: { ...form.config, sample_count: +e.target.value } })} /></Field>
          <Field label="Judges (multi-judge consensus)"><input type="number" min={1} max={5} className="input"
            value={form.config.judges}
            onChange={(e) => setForm({ ...form, config: { ...form.config, judges: +e.target.value } })} /></Field>
          <Field label="Max refinement retries"><input type="number" min={0} max={6} className="input"
            value={form.config.max_retries}
            onChange={(e) => setForm({ ...form, config: { ...form.config, max_retries: +e.target.value } })} /></Field>
          <Field label="Approval threshold"><input type="number" min={0} max={100} className="input"
            value={form.config.approval_threshold}
            onChange={(e) => setForm({ ...form, config: { ...form.config, approval_threshold: +e.target.value } })} /></Field>
          <Field label="Dataset style">
            <select className="input" value={form.config.dataset_style}
              onChange={(e) => setForm({ ...form, config: { ...form.config, dataset_style: e.target.value as 'instruction' } })}>
              <option value="instruction">instruction</option>
              <option value="chat">chat</option>
              <option value="evaluation">evaluation</option>
            </select>
          </Field>
          <Field label="Provider / model">
            <div className="flex gap-2">
              <select className="input" value={form.config.provider}
                onChange={(e) => setForm({ ...form, config: { ...form.config, provider: e.target.value } })}>
                <option value="mock">mock</option><option value="openai">openai</option>
                <option value="gemini">gemini</option><option value="anthropic">anthropic</option>
              </select>
              <input className="input" value={form.config.model}
                onChange={(e) => setForm({ ...form, config: { ...form.config, model: e.target.value } })} />
            </div>
          </Field>
          <div className="sm:col-span-2 flex items-center gap-4 text-xs text-slate-400">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={form.config.use_planner}
                onChange={(e) => setForm({ ...form, config: { ...form.config, use_planner: e.target.checked } })} />
              Enable planner agent
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={form.config.human_review_enabled}
                onChange={(e) => setForm({ ...form, config: { ...form.config, human_review_enabled: e.target.checked } })} />
              Route borderline samples to human review
            </label>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={() => setOpen(false)} className="btn-ghost btn-sm">Cancel</button>
          <button onClick={create} disabled={busy === 'create'} className="btn-primary btn-sm">
            {busy === 'create' ? 'Creating…' : 'Create workflow'}
          </button>
        </div>
      </Modal>
    </>
  );
}
