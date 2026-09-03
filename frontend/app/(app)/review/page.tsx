'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Check, Pencil, X } from 'lucide-react';
import { PageHeader } from '@/components/Shell';
import { Bar, Empty, ErrorState, Panel, Spinner, Stat } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { cn, scoreTone } from '@/lib/utils';

export default function ReviewPage() {
  const queue = useAsync(() => api.reviewQueue(), [], { poll: 6000 });
  const analytics = useAsync(() => api.evaluationAnalytics(), [], { poll: 10000 });
  const [busy, setBusy] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});

  async function act(id: string, kind: 'approve' | 'reject' | 'edit') {
    setBusy(id);
    try {
      const feedback = drafts[id] || '';
      if (kind === 'approve') await api.approveSample(id, { reviewer: 'reviewer@aura-eval', feedback });
      else if (kind === 'reject') await api.rejectSample(id, { reviewer: 'reviewer@aura-eval', feedback });
      else await api.editSample(id, { reviewer: 'reviewer@aura-eval', feedback,
        edited_payload: { response: edits[id] } });
      await queue.refresh(true);
    } finally { setBusy(null); }
  }

  if (queue.loading && !queue.data) return <Spinner label="Loading review queue…" />;
  if (queue.error) return <ErrorState error={queue.error} onRetry={() => queue.refresh()} />;

  const items = queue.data || [];

  return (
    <>
      <PageHeader title="Human Review"
        description="Borderline scores and judge disagreements are escalated here instead of being silently rejected." />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Pending review" value={items.length} tone={items.length ? 'text-warn' : 'text-ok'} />
        <Stat label="Judge disagreement" value={`${analytics.data?.judge_disagreement_rate ?? 0}%`} />
        <Stat label="Refinement success" value={`${analytics.data?.refinement_success_rate ?? 0}%`} tone="text-ok" />
        <Stat label="Avg score" value={analytics.data?.average_score?.toFixed(1) ?? '—'}
          tone={scoreTone(analytics.data?.average_score)} />
      </div>

      <div className="mt-4 space-y-4">
        {items.length === 0 ? (
          <Panel><Empty title="Review queue is empty"
            hint="Samples arrive here when judges disagree or a score falls in the borderline band." /></Panel>
        ) : items.map((s) => {
          const evaluation = (s.evaluations || []).filter((e) => e.is_consensus).slice(-1)[0];
          return (
            <Panel key={s.id} title={s.sample_key}
              subtitle={`${String(s.payload?.category ?? '')} · retries ${s.retry_count}`}
              actions={
                <span className={cn('mono text-sm', scoreTone(s.final_score ?? evaluation?.overall_score))}>
                  {(s.final_score ?? evaluation?.overall_score ?? 0).toFixed(1)}
                </span>
              }>
              <div className="grid gap-4 lg:grid-cols-2">
                <div>
                  <div className="label">Input</div>
                  <p className="text-sm text-slate-300">{String(s.payload?.input ?? '')}</p>
                  <div className="label mt-3">Response</div>
                  <textarea className="input h-40 resize-y font-mono text-xs"
                    value={edits[s.id] ?? String(s.payload?.response ?? '')}
                    onChange={(e) => setEdits({ ...edits, [s.id]: e.target.value })} />
                </div>
                <div>
                  <div className="label">Why it was escalated</div>
                  <p className="rounded-md border border-warn/20 bg-warn/5 px-3 py-2 text-xs text-warn">
                    {s.failure_reason || 'borderline score or judge disagreement'}
                  </p>
                  {evaluation && (
                    <>
                      <div className="label mt-3">Dimension scores</div>
                      <div className="space-y-2">
                        {Object.entries(evaluation.scores || {}).map(([k, v]) => (
                          <div key={k}>
                            <div className="mb-1 flex justify-between text-2xs text-slate-500">
                              <span>{k.replace(/_/g, ' ')}</span><span className="mono">{v}/10</span>
                            </div>
                            <Bar value={Number(v)} max={10}
                              tone={Number(v) >= 8 ? 'bg-ok' : Number(v) >= 6 ? 'bg-accent' : 'bg-danger'} />
                          </div>
                        ))}
                      </div>
                      <p className="mt-3 text-xs text-slate-500">{evaluation.reasoning_summary}</p>
                    </>
                  )}
                  <div className="label mt-3">Reviewer feedback</div>
                  <textarea className="input h-16 resize-y" placeholder="Why are you approving or rejecting?"
                    value={drafts[s.id] ?? ''} onChange={(e) => setDrafts({ ...drafts, [s.id]: e.target.value })} />
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button disabled={busy === s.id} onClick={() => act(s.id, 'approve')} className="btn-primary btn-sm">
                      <Check className="h-3.5 w-3.5" /> Approve</button>
                    <button disabled={busy === s.id} onClick={() => act(s.id, 'reject')} className="btn-danger btn-sm">
                      <X className="h-3.5 w-3.5" /> Reject</button>
                    <button disabled={busy === s.id || !edits[s.id]} onClick={() => act(s.id, 'edit')} className="btn-ghost btn-sm">
                      <Pencil className="h-3.5 w-3.5" /> Save edit & approve</button>
                    <Link href={`/samples/${s.id}`} className="btn-ghost btn-sm">Full inspector</Link>
                  </div>
                </div>
              </div>
            </Panel>
          );
        })}
      </div>
    </>
  );
}
