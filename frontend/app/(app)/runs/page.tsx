'use client';

import Link from 'next/link';
import { PageHeader } from '@/components/Shell';
import { Bar, Empty, ErrorState, Panel, Spinner, StatusChip } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { fmt } from '@/lib/utils';

export default function RunsPage() {
  const runs = useAsync(() => api.runs(), [], { poll: 3000 });
  if (runs.loading && !runs.data) return <Spinner label="Loading runs…" />;
  if (runs.error) return <ErrorState error={runs.error} onRetry={() => runs.refresh()} />;

  const list = runs.data || [];
  const active = list.filter((r) => r.status === 'RUNNING' || r.status === 'PENDING');

  return (
    <>
      <PageHeader title="Live Runs"
        description="Every workflow execution, with live progress. Updates stream over SSE and fall back to polling."
        actions={<Link href="/workflows" className="btn-primary btn-sm">Start a workflow</Link>} />

      {active.length > 0 && (
        <div className="mb-5 grid gap-3 lg:grid-cols-2">
          {active.map((r) => {
            const done = r.samples_approved + r.samples_rejected + r.samples_review + r.samples_failed;
            const pct = r.samples_generated ? (done / r.samples_generated) * 100 : 0;
            return (
              <Link key={r.id} href={`/runs/${r.id}`} className="panel block p-4 hover:border-accent/40">
                <div className="flex items-center justify-between">
                  <span className="mono text-sm text-slate-200">{r.id.slice(0, 8)}</span>
                  <StatusChip status={r.status} />
                </div>
                <div className="mt-2 text-xs text-slate-500">
                  {done}/{r.samples_generated || '?'} samples · step {r.steps_executed}
                </div>
                <div className="mt-2"><Bar value={pct} /></div>
              </Link>
            );
          })}
        </div>
      )}

      <Panel title="All runs" bodyClass="p-0">
        {list.length === 0 ? (
          <Empty title="No runs yet" hint="Start a workflow to see executions here."
            action={<Link href="/workflows" className="btn-primary btn-sm">Workflows</Link>} />
        ) : (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead><tr>
                <th>Run</th><th>Status</th><th>Steps</th><th>Generated</th><th>Approved</th>
                <th>Rejected</th><th>Review</th><th>Failed</th><th>Tokens</th><th>Cost</th><th>Created</th><th />
              </tr></thead>
              <tbody>
                {list.map((r) => (
                  <tr key={r.id}>
                    <td className="mono text-slate-400">{r.id.slice(0, 8)}</td>
                    <td><StatusChip status={r.status} /></td>
                    <td className="mono">{r.steps_executed}</td>
                    <td className="mono">{r.samples_generated}</td>
                    <td className="mono text-ok">{r.samples_approved}</td>
                    <td className="mono text-danger">{r.samples_rejected}</td>
                    <td className="mono text-warn">{r.samples_review}</td>
                    <td className="mono text-slate-500">{r.samples_failed}</td>
                    <td className="mono text-slate-400">{fmt.tokens(r.total_input_tokens + r.total_output_tokens)}</td>
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
