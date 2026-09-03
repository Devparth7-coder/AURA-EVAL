'use client';

import { useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useMemo, useState } from 'react';
import { PageHeader } from '@/components/Shell';
import { Empty, ErrorState, Json, Panel, Spinner, Stat, StatusChip } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { cn, fmt } from '@/lib/utils';
import type { AgentRunTrace } from '@/lib/types';

const AGENT_TONE: Record<string, string> = {
  planner: 'bg-violet', generator: 'bg-accent', evaluator: 'bg-accent-soft',
  refiner: 'bg-warn', approval: 'bg-ok', dataset_builder: 'bg-ok',
};

function TraceView() {
  const params = useSearchParams();
  const runs = useAsync(() => api.runs(), []);
  const [runId, setRunId] = useState(params.get('run') || '');
  const [selected, setSelected] = useState<AgentRunTrace | null>(null);

  useEffect(() => {
    if (!runId && runs.data?.length) setRunId(runs.data[0].id);
  }, [runs.data, runId]);

  const trace = useAsync(
    () => (runId ? api.runTrace(runId) : Promise.resolve([])), [runId], { poll: 5000 });

  const spans = useMemo(() => trace.data || [], [trace.data]);
  const timeline = useMemo(() => {
    if (!spans.length) return { start: 0, total: 1 };
    const times = spans.map((s) => new Date(`${s.created_at}Z`).getTime());
    const start = Math.min(...times);
    const end = Math.max(...times.map((t, i) => t + spans[i].latency_ms));
    return { start, total: Math.max(1, end - start) };
  }, [spans]);

  const totals = useMemo(() => ({
    calls: spans.length,
    latency: spans.reduce((a, s) => a + s.latency_ms, 0),
    tokens: spans.reduce((a, s) => a + s.input_tokens + s.output_tokens, 0),
    cost: spans.reduce((a, s) => a + s.cost_usd, 0),
    errors: spans.filter((s) => s.status === 'FAILED').length,
  }), [spans]);

  return (
    <>
      <PageHeader title="Execution Traces"
        description="Every agent invocation: input, model, output, latency, tokens, cost and status."
        actions={
          <select className="input max-w-[260px]" value={runId} onChange={(e) => { setRunId(e.target.value); setSelected(null); }}>
            {(runs.data || []).map((r) => (
              <option key={r.id} value={r.id}>{r.id.slice(0, 8)} · {r.status.toLowerCase()}</option>
            ))}
          </select>
        } />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Spans" value={totals.calls} />
        <Stat label="Total latency" value={fmt.ms(totals.latency)} />
        <Stat label="Tokens" value={fmt.tokens(totals.tokens)} />
        <Stat label="Cost" value={fmt.usd(totals.cost)} />
        <Stat label="Errors" value={totals.errors} tone={totals.errors ? 'text-danger' : 'text-ok'} />
      </div>

      {trace.error ? <ErrorState error={trace.error} onRetry={() => trace.refresh()} /> :
        trace.loading && !trace.data ? <Spinner /> : (
          <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_400px]">
            <Panel title="Trace waterfall" subtitle={`${spans.length} agent spans`} bodyClass="p-0">
              {spans.length === 0 ? <Empty title="No spans for this run" /> : (
                <div className="max-h-[620px] overflow-auto">
                  {spans.map((s) => {
                    const offset = ((new Date(`${s.created_at}Z`).getTime() - timeline.start) / timeline.total) * 100;
                    const width = Math.max(1.2, (s.latency_ms / timeline.total) * 100);
                    return (
                      <button key={s.id} onClick={() => setSelected(s)}
                        className={cn('block w-full border-b border-line/40 px-3 py-2 text-left transition-colors hover:bg-base-850/70',
                          selected?.id === s.id && 'bg-base-850')}>
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex min-w-0 items-center gap-2">
                            <span className="mono w-28 shrink-0 truncate text-2xs text-slate-300">{s.agent}</span>
                            <span className="mono truncate text-2xs text-slate-600">{s.model}</span>
                          </div>
                          <div className="flex shrink-0 items-center gap-2 text-2xs">
                            {s.error_type && <span className="text-danger">{s.error_type}</span>}
                            <span className="mono text-slate-500">{fmt.ms(s.latency_ms)}</span>
                            <StatusChip status={s.status} />
                          </div>
                        </div>
                        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-base-800">
                          <div className={cn('h-full rounded-full',
                            s.status === 'FAILED' ? 'bg-danger' : AGENT_TONE[s.agent] || 'bg-slate-600')}
                            style={{ marginLeft: `${Math.min(97, offset)}%`, width: `${Math.min(100 - offset, width)}%` }} />
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </Panel>

            <Panel title={selected ? `Span · ${selected.agent}` : 'Span detail'}
              subtitle={selected ? fmt.date(selected.created_at) : 'Select a span'}>
              {!selected ? <Empty title="No span selected" hint="Click a row in the waterfall." /> : (
                <div className="space-y-2 text-sm">
                  <div className="kv"><span className="text-slate-500">Status</span><StatusChip status={selected.status} /></div>
                  <div className="kv"><span className="text-slate-500">Provider</span><span className="mono text-slate-300">{selected.provider}</span></div>
                  <div className="kv"><span className="text-slate-500">Model</span><span className="mono text-slate-300">{selected.model}</span></div>
                  <div className="kv"><span className="text-slate-500">Prompt</span>
                    <span className="mono text-slate-300">{selected.prompt_key || '—'} v{selected.prompt_version}</span></div>
                  <div className="kv"><span className="text-slate-500">Attempt</span><span className="mono text-slate-300">{selected.attempt}</span></div>
                  <div className="kv"><span className="text-slate-500">Latency</span><span className="mono text-slate-300">{fmt.ms(selected.latency_ms)}</span></div>
                  <div className="kv"><span className="text-slate-500">Tokens</span>
                    <span className="mono text-slate-300">{selected.input_tokens} in / {selected.output_tokens} out</span></div>
                  <div className="kv"><span className="text-slate-500">Cost</span><span className="mono text-slate-300">{fmt.usd(selected.cost_usd)}</span></div>
                  {selected.error_message && (
                    <div className="rounded-md border border-danger/25 bg-danger/5 p-2.5">
                      <div className="mono text-2xs text-danger">{selected.error_type}</div>
                      <p className="mt-1 text-2xs text-slate-400">{selected.error_message}</p>
                    </div>
                  )}
                  <div><div className="label mt-3">Input</div><Json data={selected.input_json} /></div>
                  <div><div className="label mt-3">Output</div><Json data={selected.output_json} /></div>
                </div>
              )}
            </Panel>
          </div>
        )}
    </>
  );
}

export default function TracesPage() {
  return <Suspense fallback={<Spinner />}><TraceView /></Suspense>;
}
