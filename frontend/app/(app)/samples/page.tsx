'use client';

import Link from 'next/link';
import { useState } from 'react';
import { PageHeader } from '@/components/Shell';
import { Empty, ErrorState, Panel, Spinner, StatusChip } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { cn, fmt, scoreTone } from '@/lib/utils';

const STATUSES = ['', 'AUTO_APPROVED', 'HUMAN_APPROVED', 'AUTO_REJECTED',
  'HUMAN_REJECTED', 'NEEDS_REVIEW', 'FAILED'];

export default function SamplesPage() {
  const [status, setStatus] = useState('');
  const [runId, setRunId] = useState('');
  const [q, setQ] = useState('');
  const runs = useAsync(() => api.runs(), []);
  const samples = useAsync(
    () => api.samples({ status: status || undefined, run_id: runId || undefined, limit: 300 }),
    [status, runId],
  );

  const rows = (samples.data || []).filter((s) =>
    !q || JSON.stringify(s.payload).toLowerCase().includes(q.toLowerCase()));

  return (
    <>
      <PageHeader title="Samples"
        description="Every generated sample with its status, consensus score and refinement count." />

      <div className="mb-4 flex flex-wrap gap-2">
        <select className="input max-w-[200px]" value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUSES.map((s) => <option key={s} value={s}>{s ? s.replace(/_/g, ' ').toLowerCase() : 'all statuses'}</option>)}
        </select>
        <select className="input max-w-[220px]" value={runId} onChange={(e) => setRunId(e.target.value)}>
          <option value="">all runs</option>
          {(runs.data || []).map((r) => (
            <option key={r.id} value={r.id}>{r.id.slice(0, 8)} · {r.status.toLowerCase()}</option>
          ))}
        </select>
        <input className="input max-w-xs" placeholder="Search content…" value={q}
          onChange={(e) => setQ(e.target.value)} />
      </div>

      {samples.loading && !samples.data ? <Spinner /> :
        samples.error ? <ErrorState error={samples.error} onRetry={() => samples.refresh()} /> : (
          <Panel bodyClass="p-0" subtitle={`${rows.length} samples`}>
            {rows.length === 0 ? <Empty title="No samples match" hint="Adjust the filters or run a workflow." /> : (
              <div className="overflow-x-auto">
                <table className="table-base">
                  <thead><tr><th>Key</th><th>Input</th><th>Category</th><th>Difficulty</th>
                    <th>Status</th><th>Score</th><th>Retries</th><th>Created</th><th /></tr></thead>
                  <tbody>
                    {rows.map((s) => (
                      <tr key={s.id}>
                        <td className="mono text-slate-400">{s.sample_key}</td>
                        <td className="max-w-sm truncate text-slate-300">{String(s.payload?.input ?? '')}</td>
                        <td className="text-2xs text-slate-500">{String(s.payload?.category ?? '—')}</td>
                        <td className="text-2xs text-slate-500">{String(s.payload?.difficulty ?? '—')}</td>
                        <td><StatusChip status={s.status} /></td>
                        <td className={cn('mono', scoreTone(s.final_score))}>
                          {s.final_score !== null ? s.final_score.toFixed(1) : '—'}</td>
                        <td className="mono text-slate-400">{s.retry_count}</td>
                        <td className="text-2xs text-slate-500">{fmt.ago(s.created_at)}</td>
                        <td className="text-right"><Link href={`/samples/${s.id}`} className="btn-ghost btn-sm">Inspect</Link></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        )}
    </>
  );
}
