'use client';

import Link from 'next/link';
import { Download } from 'lucide-react';
import { PageHeader } from '@/components/Shell';
import { Empty, ErrorState, Panel, Spinner, Stat } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { fmt } from '@/lib/utils';

export default function DatasetsPage() {
  const datasets = useAsync(() => api.datasets(), [], { poll: 8000 });
  if (datasets.loading && !datasets.data) return <Spinner label="Loading datasets…" />;
  if (datasets.error) return <ErrorState error={datasets.error} onRetry={() => datasets.refresh()} />;

  const list = datasets.data || [];
  const totalRows = list.reduce((a, d) => a + d.row_count, 0);

  return (
    <>
      <PageHeader title="Datasets"
        description="Approved samples transformed into instruction, chat or evaluation datasets and exported in multiple formats." />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Datasets" value={list.length} />
        <Stat label="Total rows" value={fmt.num(totalRows)} tone="text-ok" />
        <Stat label="Styles" value={new Set(list.map((d) => d.style)).size || 0} />
        <Stat label="Artifacts" value={list.reduce((a, d) => a + d.versions.length, 0)} />
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {list.length === 0 ? (
          <div className="lg:col-span-2 xl:col-span-3">
            <Panel><Empty title="No datasets yet"
              hint="Run a workflow — the dataset builder agent produces one automatically from approved samples."
              action={<Link href="/workflows" className="btn-primary btn-sm">Go to workflows</Link>} /></Panel>
          </div>
        ) : list.map((d) => (
          <div key={d.id} className="panel flex flex-col p-4 transition-colors hover:border-slate-700">
            <Link href={`/datasets/${d.id}`} className="min-w-0">
              <h3 className="truncate text-sm font-semibold text-slate-100 hover:text-accent-soft">{d.name}</h3>
            </Link>
            <div className="mt-2 flex flex-wrap gap-2 text-2xs">
              <span className="chip border-accent/25 bg-accent/10 text-accent">{d.style}</span>
              <span className="chip border-line text-slate-400">{d.row_count} rows</span>
              <span className="chip border-line text-slate-500">v{d.current_version}</span>
            </div>
            {d.dataset_metadata?.objective && (
              <p className="mt-2 line-clamp-2 text-xs text-slate-500">{String(d.dataset_metadata.objective)}</p>
            )}
            <div className="mt-3 flex flex-wrap gap-1.5 border-t border-line pt-3">
              {d.versions.map((v) => (
                <a key={v.id} href={api.downloadUrl(d.id, v.fmt)} className="btn-ghost btn-sm">
                  <Download className="h-3 w-3" /> {v.fmt}
                  <span className="text-slate-600">{fmt.bytes(v.size_bytes)}</span>
                </a>
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between text-2xs text-slate-600">
              <span>{fmt.ago(d.created_at)}</span>
              <Link href={`/datasets/${d.id}`} className="text-accent hover:underline">Explore →</Link>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
