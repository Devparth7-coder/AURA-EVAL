'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Download } from 'lucide-react';
import { PageHeader } from '@/components/Shell';
import { Empty, ErrorState, Json, Panel, Spinner, Stat } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { cn, fmt } from '@/lib/utils';

export default function DatasetDetail() {
  const { id } = useParams<{ id: string }>();
  const dataset = useAsync(() => api.dataset(id), [id]);
  const preview = useAsync(() => api.datasetPreview(id, 50), [id]);
  const [view, setView] = useState<'table' | 'json'>('table');
  const [row, setRow] = useState(0);

  if (dataset.loading && !dataset.data) return <Spinner label="Loading dataset…" />;
  if (dataset.error) return <ErrorState error={dataset.error} onRetry={() => dataset.refresh()} />;

  const d = dataset.data!;
  const rows = preview.data?.rows || [];
  const columns = rows.length ? Object.keys(rows[0]) : [];

  return (
    <>
      <PageHeader title={d.name} description={`${d.style} dataset · ${d.row_count} rows`}
        actions={
          <>
            {d.run_id && <Link href={`/runs/${d.run_id}`} className="btn-ghost btn-sm">Source run</Link>}
            {d.versions.map((v) => (
              <a key={v.id} href={api.downloadUrl(d.id, v.fmt)} className="btn-primary btn-sm">
                <Download className="h-3.5 w-3.5" /> {v.fmt.toUpperCase()}
              </a>
            ))}
          </>
        } />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Rows" value={fmt.num(d.row_count)} tone="text-ok" />
        <Stat label="Style" value={d.style} />
        <Stat label="Artifacts" value={d.versions.length} />
        <Stat label="Created" value={fmt.ago(d.created_at)} />
      </div>

      <Panel className="mt-4" title="Artifacts" subtitle="Serialised exports with integrity checksums" bodyClass="p-0">
        <div className="overflow-x-auto">
          <table className="table-base">
            <thead><tr><th>Format</th><th>Rows</th><th>Size</th><th>Checksum</th><th>Storage key</th><th /></tr></thead>
            <tbody>
              {d.versions.map((v) => (
                <tr key={v.id}>
                  <td className="mono uppercase text-slate-200">{v.fmt}</td>
                  <td className="mono">{v.row_count}</td>
                  <td className="mono text-slate-400">{fmt.bytes(v.size_bytes)}</td>
                  <td className="mono max-w-[160px] truncate text-2xs text-slate-600">{v.checksum}</td>
                  <td className="mono max-w-[200px] truncate text-2xs text-slate-600">{v.storage_key || 'inline'}</td>
                  <td className="text-right">
                    <a href={api.downloadUrl(d.id, v.fmt)} className="btn-ghost btn-sm">
                      <Download className="h-3 w-3" /> Download</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel className="mt-4" title="Preview" subtitle={`First ${rows.length} rows`}
        actions={
          <div className="flex gap-1">
            {(['table', 'json'] as const).map((v) => (
              <button key={v} onClick={() => setView(v)}
                className={cn('btn-sm rounded-md border px-2.5 py-1',
                  view === v ? 'border-accent/40 bg-accent/10 text-accent' : 'border-line text-slate-400')}>
                {v}
              </button>
            ))}
          </div>
        } bodyClass={view === 'table' ? 'p-0' : undefined}>
        {rows.length === 0 ? <Empty title="No rows to preview" /> : view === 'json' ? (
          <div className="grid gap-3 lg:grid-cols-[200px_1fr]">
            <div className="max-h-96 overflow-y-auto rounded-lg border border-line">
              {rows.map((_, i) => (
                <button key={i} onClick={() => setRow(i)}
                  className={cn('block w-full border-b border-line/40 px-3 py-1.5 text-left mono text-2xs',
                    row === i ? 'bg-accent/10 text-accent' : 'text-slate-500 hover:bg-base-850')}>
                  row {i + 1}
                </button>
              ))}
            </div>
            <Json data={rows[row]} className="max-h-96" />
          </div>
        ) : (
          <div className="max-h-[500px] overflow-auto">
            <table className="table-base">
              <thead><tr><th>#</th>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td className="mono text-slate-600">{i + 1}</td>
                    {columns.map((c) => (
                      <td key={c} className="max-w-md">
                        <div className="line-clamp-3 text-xs">
                          {typeof r[c] === 'object' ? JSON.stringify(r[c]) : String(r[c] ?? '')}
                        </div>
                      </td>
                    ))}
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
