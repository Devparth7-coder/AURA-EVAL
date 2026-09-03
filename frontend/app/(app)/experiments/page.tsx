'use client';

import { useState } from 'react';
import { Plus, Trophy } from 'lucide-react';
import { PageHeader } from '@/components/Shell';
import { Empty, ErrorState, Field, Modal, Panel, Spinner, StatusChip } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { cn, fmt } from '@/lib/utils';

function formatValue(v: number, unit: string) {
  if (unit === 'pct') return `${v.toFixed(1)}%`;
  if (unit === 'usd') return fmt.usd(v);
  if (unit === 's') return `${v.toFixed(2)}s`;
  return v.toFixed(2);
}

export default function ExperimentsPage() {
  const experiments = useAsync(() => api.experiments(), [], { poll: 4000 });
  const projects = useAsync(() => api.projects(), []);
  const sops = useAsync(() => api.sops(), []);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: 'Model A vs Model B', objective: 'Compare model quality on Python coding questions',
    sample_count: 5, sop_id: '',
    arms: [
      { label: 'Model A', provider: 'mock', model: 'mock-1', prompt_version: 1, quality_bias: 0 },
      { label: 'Model B', provider: 'mock', model: 'mock-1', prompt_version: 2, quality_bias: 0.4 },
    ],
  });

  async function create() {
    setBusy(true);
    try {
      const exp = await api.createExperiment({
        ...form, project_id: projects.data?.[0]?.id ?? null,
        sop_id: form.sop_id || null,
      });
      setOpen(false);
      setSelected(exp.id);
      await experiments.refresh(true);
    } finally { setBusy(false); }
  }

  if (experiments.loading && !experiments.data) return <Spinner label="Loading experiments…" />;
  if (experiments.error) return <ErrorState error={experiments.error} onRetry={() => experiments.refresh()} />;

  const list = experiments.data || [];
  const active = list.find((e) => e.id === selected) || list[0];
  const report = active?.report;

  return (
    <>
      <PageHeader title="Experiments"
        description="Run the same objective across model or prompt-version arms and compare quality, latency and cost."
        actions={<button onClick={() => setOpen(true)} className="btn-primary btn-sm">
          <Plus className="h-3.5 w-3.5" /> New experiment</button>} />

      <div className="grid gap-4 xl:grid-cols-[260px_1fr]">
        <Panel title="Experiments" bodyClass="p-0">
          {list.length === 0 ? <Empty title="No experiments" /> : list.map((e) => (
            <button key={e.id} onClick={() => setSelected(e.id)}
              className={cn('block w-full border-b border-line/40 px-3 py-2.5 text-left',
                active?.id === e.id ? 'bg-accent/10' : 'hover:bg-base-850')}>
              <div className="flex items-center justify-between gap-2">
                <span className={cn('truncate text-sm', active?.id === e.id ? 'text-accent-soft' : 'text-slate-300')}>
                  {e.name}</span>
                <StatusChip status={e.status} />
              </div>
              <div className="mt-0.5 text-2xs text-slate-600">{fmt.ago(e.created_at)}</div>
            </button>
          ))}
        </Panel>

        <div className="space-y-4">
          {!active ? (
            <Panel><Empty title="No experiment selected"
              hint="Create an experiment to compare two or more model / prompt configurations."
              action={<button onClick={() => setOpen(true)} className="btn-primary btn-sm">Create experiment</button>} /></Panel>
          ) : active.status !== 'COMPLETED' ? (
            <Panel title={active.name} subtitle={active.description}>
              <div className="flex items-center gap-3 py-8">
                <Spinner label={`Experiment ${active.status.toLowerCase()} — executing arms…`} />
              </div>
            </Panel>
          ) : (
            <>
              <Panel title={active.name} subtitle={active.description}
                actions={report?.winner && (
                  <span className="chip border-ok/30 bg-ok/10 text-ok">
                    <Trophy className="h-3 w-3" /> {report.winner}</span>
                )}>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {(report?.arms || []).map((arm) => (
                    <div key={arm.label} className={cn('rounded-lg border p-3',
                      report?.winner === arm.label ? 'border-ok/35 bg-ok/[0.05]' : 'border-line bg-base-850/50')}>
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-semibold text-slate-200">{arm.label}</span>
                        <span className="mono text-2xs text-slate-500">{report?.wins?.[arm.label] ?? 0} wins</span>
                      </div>
                      <div className="mt-1 space-y-0.5 text-2xs text-slate-500">
                        <div>{arm.provider} · {arm.model}</div>
                        <div>evaluator prompt v{arm.prompt_version}</div>
                        <div>{arm.metrics?.samples ?? 0} samples · {arm.metrics?.approved ?? 0} approved</div>
                      </div>
                    </div>
                  ))}
                </div>
              </Panel>

              <Panel title="Comparison report" subtitle="Winner highlighted per metric" bodyClass="p-0">
                <div className="overflow-x-auto">
                  <table className="table-base">
                    <thead>
                      <tr>
                        <th>Metric</th>
                        {(report?.arms || []).map((a) => <th key={a.label} className="text-right">{a.label}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {(report?.comparison || []).map((row) => (
                        <tr key={row.metric}>
                          <td className="text-slate-300">{row.label}</td>
                          {(report?.arms || []).map((a) => {
                            const v = row.values[a.label] ?? 0;
                            const win = row.winner === a.label;
                            return (
                              <td key={a.label} className="text-right">
                                <span className={cn('mono', win ? 'font-semibold text-ok' : 'text-slate-400')}>
                                  {formatValue(v, row.unit)}
                                </span>
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </>
          )}
        </div>
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title="Create experiment" wide>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name"><input className="input" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Samples per arm"><input type="number" min={1} max={30} className="input"
            value={form.sample_count} onChange={(e) => setForm({ ...form, sample_count: +e.target.value })} /></Field>
          <div className="sm:col-span-2">
            <Field label="Objective"><input className="input" value={form.objective}
              onChange={(e) => setForm({ ...form, objective: e.target.value })} /></Field>
          </div>
          <div className="sm:col-span-2">
            <Field label="SOP">
              <select className="input" value={form.sop_id} onChange={(e) => setForm({ ...form, sop_id: e.target.value })}>
                <option value="">Default SOP</option>
                {(sops.data || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </Field>
          </div>
        </div>

        <div className="mt-4">
          <div className="label">Arms</div>
          {form.arms.map((arm, i) => (
            <div key={i} className="mb-2 grid gap-2 rounded-lg border border-line bg-base-850/50 p-3 sm:grid-cols-5">
              <input className="input py-1.5" value={arm.label} placeholder="Label"
                onChange={(e) => setForm({ ...form, arms: form.arms.map((a, j) => j === i ? { ...a, label: e.target.value } : a) })} />
              <select className="input py-1.5" value={arm.provider}
                onChange={(e) => setForm({ ...form, arms: form.arms.map((a, j) => j === i ? { ...a, provider: e.target.value } : a) })}>
                <option value="mock">mock</option><option value="openai">openai</option>
                <option value="gemini">gemini</option><option value="anthropic">anthropic</option>
              </select>
              <input className="input py-1.5" value={arm.model} placeholder="model"
                onChange={(e) => setForm({ ...form, arms: form.arms.map((a, j) => j === i ? { ...a, model: e.target.value } : a) })} />
              <input type="number" min={1} className="input py-1.5" value={arm.prompt_version}
                title="Evaluator prompt version"
                onChange={(e) => setForm({ ...form, arms: form.arms.map((a, j) => j === i ? { ...a, prompt_version: +e.target.value } : a) })} />
              <input type="number" step={0.1} min={-1} max={1} className="input py-1.5" value={arm.quality_bias}
                title="Mock quality bias (demo mode)"
                onChange={(e) => setForm({ ...form, arms: form.arms.map((a, j) => j === i ? { ...a, quality_bias: +e.target.value } : a) })} />
            </div>
          ))}
          {form.arms.length < 4 && (
            <button className="btn-ghost btn-sm"
              onClick={() => setForm({ ...form, arms: [...form.arms, { label: `Model ${String.fromCharCode(65 + form.arms.length)}`, provider: 'mock', model: 'mock-1', prompt_version: 1, quality_bias: 0 }] })}>
              <Plus className="h-3.5 w-3.5" /> Add arm</button>
          )}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button onClick={() => setOpen(false)} className="btn-ghost btn-sm">Cancel</button>
          <button onClick={create} disabled={busy} className="btn-primary btn-sm">
            {busy ? 'Launching…' : 'Run experiment'}</button>
        </div>
      </Modal>
    </>
  );
}
