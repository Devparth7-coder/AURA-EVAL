'use client';

import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { Play } from 'lucide-react';
import { PageHeader } from '@/components/Shell';
import { WorkflowGraph } from '@/components/WorkflowGraph';
import { Empty, ErrorState, Json, Panel, Spinner, StatusChip } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { fmt } from '@/lib/utils';
import type { NodeStats } from '@/lib/types';

export default function WorkflowDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const workflow = useAsync(() => api.workflow(id), [id]);
  const runs = useAsync(() => api.workflowRuns(id), [id], { poll: 5000 });
  const topology = useAsync(() => api.topology(), []);
  const latestRunId = runs.data?.[0]?.id ?? null;
  const graph = useAsync(
    () => (latestRunId ? api.runGraph(latestRunId) : Promise.resolve(null)),
    [latestRunId], { poll: 4000 },
  );
  const [selected, setSelected] = useState<string | null>('critic');
  const [busy, setBusy] = useState(false);

  if (workflow.loading && !workflow.data) return <Spinner label="Loading workflow…" />;
  if (workflow.error) return <ErrorState error={workflow.error} onRetry={() => workflow.refresh()} />;

  const wf = workflow.data!;
  const cfg = wf.config || {};
  const nodes = graph.data?.nodes ?? topology.data?.nodes ?? [];
  const edges = graph.data?.edges ?? topology.data?.edges ?? [];
  const stats = graph.data?.stats;
  const node = nodes.find((n) => n.id === selected);
  const nodeStats: NodeStats | undefined = selected ? stats?.[selected] : undefined;

  async function start() {
    setBusy(true);
    try {
      const run = await api.runWorkflow(id, { async_execution: true });
      router.push(`/runs/${run.id}`);
    } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader title={wf.name} description={wf.objective}
        actions={
          <>
            {latestRunId && <Link href={`/runs/${latestRunId}`} className="btn-ghost btn-sm">Latest run</Link>}
            <button onClick={start} disabled={busy} className="btn-primary btn-sm">
              <Play className="h-3.5 w-3.5" /> {busy ? 'Starting…' : 'Run workflow'}
            </button>
          </>
        } />

      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <Panel title="Agent graph"
          subtitle="LangGraph topology with conditional PASS / FAIL routing — click a node to inspect it"
          bodyClass="p-3">
          {nodes.length === 0 ? <Spinner /> : (
            <WorkflowGraph nodes={nodes} edges={edges} stats={stats}
              activeNode={graph.data?.active_node} selected={selected} onSelect={setSelected} />
          )}
        </Panel>

        <div className="space-y-4">
          <Panel title={node ? `Node · ${node.label}` : 'Node inspector'}
            subtitle={node?.description}>
            {!node ? <Empty title="Select a node" hint="Click any agent in the graph." /> : (
              <div className="space-y-3 text-sm">
                <div className="kv"><span className="text-slate-500">Status</span>
                  <StatusChip status={nodeStats?.status ?? 'IDLE'} /></div>
                <div className="kv"><span className="text-slate-500">Model</span>
                  <span className="mono text-slate-300">{nodeStats?.model || cfg.model || '—'}</span></div>
                <div className="kv"><span className="text-slate-500">Provider</span>
                  <span className="mono text-slate-300">{nodeStats?.provider || cfg.provider || '—'}</span></div>
                <div className="kv"><span className="text-slate-500">Prompt</span>
                  <span className="mono text-slate-300">
                    {nodeStats?.prompt_key ? `${nodeStats.prompt_key} v${nodeStats.prompt_version}` : '—'}
                  </span></div>
                <div className="kv"><span className="text-slate-500">Calls</span>
                  <span className="mono text-slate-300">{nodeStats?.calls ?? 0}</span></div>
                <div className="kv"><span className="text-slate-500">Avg latency</span>
                  <span className="mono text-slate-300">{fmt.ms(nodeStats?.avg_latency_ms ?? 0)}</span></div>
                <div className="kv"><span className="text-slate-500">Tokens</span>
                  <span className="mono text-slate-300">{fmt.tokens(nodeStats?.tokens ?? 0)}</span></div>
                <div className="kv"><span className="text-slate-500">Cost</span>
                  <span className="mono text-slate-300">{fmt.usd(nodeStats?.cost_usd ?? 0)}</span></div>
                <div className="kv"><span className="text-slate-500">Errors</span>
                  <span className={nodeStats?.errors ? 'mono text-danger' : 'mono text-slate-300'}>
                    {nodeStats?.errors ?? 0}</span></div>

                {nodeStats?.last_input && Object.keys(nodeStats.last_input).length > 0 && (
                  <div>
                    <div className="label mt-3">Last input</div>
                    <Json data={nodeStats.last_input} className="max-h-40" />
                  </div>
                )}
                {nodeStats?.last_output && Object.keys(nodeStats.last_output).length > 0 && (
                  <div>
                    <div className="label mt-3">Last output</div>
                    <Json data={nodeStats.last_output} className="max-h-52" />
                  </div>
                )}
              </div>
            )}
          </Panel>

          <Panel title="Configuration" subtitle="Snapshot taken at the start of each run">
            <div className="space-y-1">
              {Object.entries(cfg).map(([k, v]) => (
                <div key={k} className="kv">
                  <span className="text-slate-500">{k.replace(/_/g, ' ')}</span>
                  <span className="mono max-w-[55%] truncate text-right text-slate-300">
                    {Array.isArray(v) ? v.join(', ') : String(v)}
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>

      <Panel className="mt-4" title="Run history" subtitle="All executions of this workflow" bodyClass="p-0">
        {(runs.data || []).length === 0 ? (
          <Empty title="No runs yet" hint="Start the workflow to produce samples and a dataset." />
        ) : (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr><th>Run</th><th>Status</th><th>Steps</th><th>Generated</th><th>Approved</th>
                  <th>Rejected</th><th>Review</th><th>Cost</th><th>Started</th><th /></tr>
              </thead>
              <tbody>
                {(runs.data || []).map((r) => (
                  <tr key={r.id}>
                    <td className="mono text-slate-400">{r.id.slice(0, 8)}</td>
                    <td><StatusChip status={r.status} /></td>
                    <td className="mono">{r.steps_executed}</td>
                    <td className="mono">{r.samples_generated}</td>
                    <td className="mono text-ok">{r.samples_approved}</td>
                    <td className="mono text-danger">{r.samples_rejected}</td>
                    <td className="mono text-warn">{r.samples_review}</td>
                    <td className="mono text-slate-400">{fmt.usd(r.total_cost_usd)}</td>
                    <td className="text-2xs text-slate-500">{fmt.ago(r.created_at)}</td>
                    <td className="text-right"><Link href={`/runs/${r.id}`} className="btn-ghost btn-sm">Open</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}
