'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircle2, CircleDot, Download, RefreshCcw, Radio, Square, XCircle, Zap,
} from 'lucide-react';
import { PageHeader } from '@/components/Shell';
import { WorkflowGraph } from '@/components/WorkflowGraph';
import { Bar, Empty, ErrorState, Json, Panel, Spinner, Stat, StatusChip } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { useRunStream } from '@/hooks/useRunStream';
import { api } from '@/lib/api';
import { cn, fmt, scoreTone } from '@/lib/utils';
import type { WorkflowEvent } from '@/lib/types';

const EVENT_ICON: Record<string, { icon: typeof CheckCircle2; tone: string }> = {
  'run.started': { icon: Zap, tone: 'text-accent' },
  'run.completed': { icon: CheckCircle2, tone: 'text-ok' },
  'run.failed': { icon: XCircle, tone: 'text-danger' },
  'run.stopped': { icon: Square, tone: 'text-warn' },
  'agent.started': { icon: CircleDot, tone: 'text-slate-400' },
  'agent.completed': { icon: CheckCircle2, tone: 'text-ok' },
  'agent.failed': { icon: XCircle, tone: 'text-danger' },
  'sample.evaluating': { icon: CircleDot, tone: 'text-accent' },
  'sample.approved': { icon: CheckCircle2, tone: 'text-ok' },
  'sample.rejected': { icon: XCircle, tone: 'text-danger' },
  'sample.needs_review': { icon: CircleDot, tone: 'text-violet' },
  'sample.failed': { icon: XCircle, tone: 'text-danger' },
  'refinement.started': { icon: RefreshCcw, tone: 'text-warn' },
  'dataset.built': { icon: Download, tone: 'text-ok' },
};

function EventRow({ e }: { e: WorkflowEvent }) {
  const meta = EVENT_ICON[e.type] ?? { icon: CircleDot, tone: 'text-slate-500' };
  const Icon = meta.icon;
  return (
    <div className="flex animate-fade-up items-start gap-2.5 border-b border-line/40 px-3 py-2 last:border-0">
      <Icon className={cn('mt-0.5 h-3.5 w-3.5 shrink-0', meta.tone,
        e.type === 'sample.evaluating' && 'animate-pulse')} />
      <div className="min-w-0 flex-1">
        <p className="text-xs leading-snug text-slate-300">{e.message}</p>
        <div className="mt-0.5 flex flex-wrap gap-2 font-mono text-[10px] text-slate-600">
          <span>#{e.seq}</span>
          <span>{e.type}</span>
          <span>{fmt.time(e.created_at)}</span>
          {typeof e.data?.score === 'number' && (
            <span className={scoreTone(e.data.score)}>score {e.data.score}</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const { events, status, transport } = useRunStream(id);
  const run = useAsync(() => api.run(id), [id], { poll: status?.terminal ? 0 : 3000 });
  const graph = useAsync(() => api.runGraph(id), [id], { poll: status?.terminal ? 0 : 3000 });
  const samples = useAsync(() => api.samples({ run_id: id, limit: 200 }), [id],
    { poll: status?.terminal ? 0 : 4000 });
  const datasets = useAsync(() => api.datasets({ run_id: id }), [id],
    { poll: status?.terminal ? 0 : 5000 });
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [autoscroll, setAutoscroll] = useState(true);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoscroll && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events.length, autoscroll]);

  const progress = useMemo(() => {
    const total = status?.samples_generated || run.data?.samples_generated || 0;
    const done = (status?.samples_approved ?? 0) + (status?.samples_rejected ?? 0)
      + (status?.samples_review ?? 0) + (status?.samples_failed ?? 0);
    return { total, done, pct: total ? (done / total) * 100 : 0 };
  }, [status, run.data]);

  if (run.loading && !run.data) return <Spinner label="Loading run…" />;
  if (run.error) return <ErrorState error={run.error} onRetry={() => run.refresh()} />;

  const r = run.data!;
  const live = !status?.terminal;
  const dataset = datasets.data?.[0];

  return (
    <>
      <PageHeader title={`Run ${r.id.slice(0, 8)}`}
        description={String((r.plan as { objective?: string })?.objective || 'Workflow execution')}
        actions={
          <>
            <span className={cn('chip', transport === 'sse' ? 'border-ok/30 bg-ok/10 text-ok'
              : transport === 'polling' ? 'border-accent/30 bg-accent/10 text-accent' : 'border-line text-slate-500')}>
              <Radio className="h-3 w-3" /> {transport}
            </span>
            <StatusChip status={status?.status ?? r.status} />
            {live && (
              <button onClick={() => api.stopRun(id).then(() => run.refresh(true))} className="btn-danger btn-sm">
                <Square className="h-3.5 w-3.5" /> Stop
              </button>
            )}
            <Link href={`/traces?run=${id}`} className="btn-ghost btn-sm">Trace</Link>
          </>
        } />

      {r.error && (
        <div className="mb-4 rounded-lg border border-danger/30 bg-danger/10 p-3">
          <div className="mono text-xs font-semibold text-danger">{String(r.error.error)}</div>
          <p className="mt-1 text-xs text-slate-400">{String(r.error.message)}</p>
          <p className="mt-1 text-2xs text-slate-600">
            node: {String(r.error.node ?? '—')} · retryable: {String(r.error.retryable)}
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat label="Generated" value={fmt.num(status?.samples_generated ?? r.samples_generated)} />
        <Stat label="Approved" value={fmt.num(status?.samples_approved ?? r.samples_approved)} tone="text-ok" />
        <Stat label="Rejected" value={fmt.num(status?.samples_rejected ?? r.samples_rejected)} tone="text-danger" />
        <Stat label="Needs review" value={fmt.num(status?.samples_review ?? r.samples_review)} tone="text-warn" />
        <Stat label="Tokens" value={fmt.tokens(status?.tokens ?? (r.total_input_tokens + r.total_output_tokens))} />
        <Stat label="Run cost" value={fmt.usd(status?.cost_usd ?? r.total_cost_usd)}
          sub={progress.total ? `${fmt.usd((status?.cost_usd ?? 0) / progress.total)} / sample` : undefined} />
      </div>

      <div className="mt-3 panel px-4 py-3">
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-400">
            {progress.done} / {progress.total || '?'} samples processed
            {status?.queue_remaining ? ` · ${status.queue_remaining} queued` : ''}
          </span>
          <span className="mono text-slate-500">
            step {status?.steps_executed ?? r.steps_executed} · node {status?.resume_at ?? '—'}
          </span>
        </div>
        <div className="mt-2"><Bar value={progress.pct} tone={live ? 'bg-accent' : 'bg-ok'} /></div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[420px_1fr]">
        <Panel title="Live execution" subtitle={`${events.length} events`} bodyClass="p-0"
          actions={
            <label className="flex items-center gap-1.5 text-2xs text-slate-500">
              <input type="checkbox" checked={autoscroll} onChange={(e) => setAutoscroll(e.target.checked)} />
              follow
            </label>
          }>
          <div ref={logRef} className="max-h-[560px] min-h-[300px] overflow-y-auto">
            {events.length === 0 ? (
              <Empty title={live ? 'Waiting for events…' : 'No events recorded'} />
            ) : events.map((e) => <EventRow key={`${e.seq}-${e.type}`} e={e} />)}
          </div>
        </Panel>

        <Panel title="Agent graph" subtitle="Live node activity" bodyClass="p-3">
          {!graph.data ? <Spinner /> : (
            <WorkflowGraph nodes={graph.data.nodes} edges={graph.data.edges} stats={graph.data.stats}
              activeNode={live ? graph.data.active_node : null} selected={selectedNode}
              onSelect={setSelectedNode} height={560} />
          )}
        </Panel>
      </div>

      {selectedNode && graph.data?.stats?.[selectedNode] && (
        <Panel className="mt-4" title={`Node output · ${selectedNode}`}
          subtitle={`${graph.data.stats[selectedNode].calls} calls · ${fmt.ms(graph.data.stats[selectedNode].avg_latency_ms)} avg`}
          actions={<button onClick={() => setSelectedNode(null)} className="btn-ghost btn-sm">Clear</button>}>
          <div className="grid gap-3 lg:grid-cols-2">
            <div><div className="label">Last input</div><Json data={graph.data.stats[selectedNode].last_input} /></div>
            <div><div className="label">Last output</div><Json data={graph.data.stats[selectedNode].last_output} /></div>
          </div>
        </Panel>
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_360px]">
        <Panel title="Samples" subtitle="Every sample produced by this run" bodyClass="p-0">
          {(samples.data || []).length === 0 ? <Empty title="No samples yet" /> : (
            <div className="max-h-[420px] overflow-auto">
              <table className="table-base">
                <thead><tr><th>Key</th><th>Input</th><th>Status</th><th>Score</th><th>Retries</th><th /></tr></thead>
                <tbody>
                  {(samples.data || []).map((s) => (
                    <tr key={s.id}>
                      <td className="mono text-slate-400">{s.sample_key}</td>
                      <td className="max-w-xs truncate text-slate-300">{String(s.payload?.input ?? '')}</td>
                      <td><StatusChip status={s.status} /></td>
                      <td className={cn('mono', scoreTone(s.final_score))}>
                        {s.final_score !== null ? s.final_score.toFixed(1) : '—'}</td>
                      <td className="mono text-slate-400">{s.retry_count}</td>
                      <td className="text-right">
                        <Link href={`/samples/${s.id}`} className="btn-ghost btn-sm">Inspect</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel title="Dataset" subtitle="Produced by the dataset builder agent">
          {!dataset ? (
            <Empty title={live ? 'Dataset pending' : 'No dataset produced'}
              hint={live ? 'Built once every sample has been processed.' : 'No samples were approved.'} />
          ) : (
            <div className="space-y-3">
              <div className="kv"><span className="text-slate-500">Name</span>
                <span className="truncate text-slate-200">{dataset.name}</span></div>
              <div className="kv"><span className="text-slate-500">Style</span>
                <span className="mono text-slate-300">{dataset.style}</span></div>
              <div className="kv"><span className="text-slate-500">Rows</span>
                <span className="mono text-slate-300">{dataset.row_count}</span></div>
              <div className="mt-3">
                <div className="label">Download</div>
                <div className="flex flex-wrap gap-2">
                  {dataset.versions.map((v) => (
                    <a key={v.id} href={api.downloadUrl(dataset.id, v.fmt)} className="btn-primary btn-sm">
                      <Download className="h-3.5 w-3.5" /> {v.fmt.toUpperCase()}
                      <span className="text-slate-500">{fmt.bytes(v.size_bytes)}</span>
                    </a>
                  ))}
                </div>
              </div>
              <Link href={`/datasets/${dataset.id}`} className="btn-ghost btn-sm mt-2 w-full">Open dataset explorer</Link>
            </div>
          )}
        </Panel>
      </div>

      <Panel className="mt-4" title="Execution plan" subtitle="Produced by the planner agent">
        {Object.keys(r.plan || {}).length === 0 ? <Empty title="No plan recorded" /> : <Json data={r.plan} />}
      </Panel>
    </>
  );
}
