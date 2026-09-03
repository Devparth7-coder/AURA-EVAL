'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { ArrowRight, Check, X } from 'lucide-react';
import { PageHeader } from '@/components/Shell';
import { Bar, Empty, ErrorState, Json, Panel, Spinner, Stat, StatusChip } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { cn, fmt, scoreTone } from '@/lib/utils';

const DIMENSIONS = ['correctness', 'relevance', 'completeness', 'instruction_following', 'safety'];

export default function SampleInspector() {
  const { id } = useParams<{ id: string }>();
  const sample = useAsync(() => api.sample(id), [id]);
  const history = useAsync(() => api.sampleHistory(id), [id]);
  const [compare, setCompare] = useState<[number, number]>([1, 2]);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');

  if (sample.loading && !sample.data) return <Spinner label="Loading sample…" />;
  if (sample.error) return <ErrorState error={sample.error} onRetry={() => sample.refresh()} />;

  const s = sample.data!;
  const timeline = history.data?.timeline || [];
  const consensus = (s.evaluations || []).filter((e) => e.is_consensus);
  const judges = (s.evaluations || []).filter((e) => !e.is_consensus);
  const latest = consensus[consensus.length - 1];
  const left = timeline.find((t) => t.version === compare[0]);
  const right = timeline.find((t) => t.version === compare[1]) ?? left;

  async function review(kind: 'approve' | 'reject') {
    setBusy(true);
    try {
      if (kind === 'approve') await api.approveSample(id, { reviewer: 'reviewer@aura-eval', feedback });
      else await api.rejectSample(id, { reviewer: 'reviewer@aura-eval', feedback });
      setFeedback('');
      await Promise.all([sample.refresh(true), history.refresh(true)]);
    } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader title={`Sample ${s.sample_key}`}
        description={String(s.payload?.category ?? '')}
        actions={
          <>
            <StatusChip status={s.status} />
            <Link href={`/runs/${s.run_id}`} className="btn-ghost btn-sm">Back to run</Link>
          </>
        } />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Final score" value={s.final_score !== null ? s.final_score.toFixed(1) : '—'}
          tone={scoreTone(s.final_score)} />
        <Stat label="Refinements" value={s.retry_count} sub={`${timeline.length} versions`} />
        <Stat label="Evaluations" value={consensus.length} sub={`${judges.length} judge verdicts`} />
        <Stat label="Confidence" value={latest ? latest.confidence.toFixed(2) : '—'} />
        <Stat label="Hallucination risk" value={latest?.hallucination_risk ?? '—'}
          tone={latest?.hallucination_risk === 'low' ? 'text-ok' : 'text-warn'} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Panel title="Input" subtitle="Original task / question">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
            {String(s.payload?.input ?? '')}
          </p>
          {s.payload?.reference && (
            <>
              <div className="label mt-4">Reference</div>
              <p className="whitespace-pre-wrap text-xs leading-relaxed text-slate-500">
                {String(s.payload.reference)}
              </p>
            </>
          )}
        </Panel>

        <Panel title="Generated output" subtitle="Current accepted version">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-300">
            {String(s.payload?.response ?? '')}
          </p>
        </Panel>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_380px]">
        <Panel title="Evaluation" subtitle="Consensus verdict and per-dimension scores">
          {!latest ? <Empty title="Not evaluated yet" /> : (
            <div className="space-y-4">
              <div className="space-y-2.5">
                {DIMENSIONS.map((d) => {
                  const v = Number(latest.scores?.[d] ?? 0);
                  return (
                    <div key={d}>
                      <div className="mb-1 flex justify-between text-xs">
                        <span className="text-slate-400">{d.replace(/_/g, ' ')}</span>
                        <span className="mono text-slate-300">{v}/10</span>
                      </div>
                      <Bar value={v} max={10} tone={v >= 8 ? 'bg-ok' : v >= 6 ? 'bg-accent' : 'bg-danger'} />
                    </div>
                  );
                })}
              </div>

              <div className="rounded-lg border border-line bg-base-850/60 p-3">
                <div className="label">Reasoning summary</div>
                <p className="text-xs leading-relaxed text-slate-400">{latest.reasoning_summary || '—'}</p>
              </div>

              {latest.issues.length > 0 && (
                <div>
                  <div className="label">Issues</div>
                  <div className="space-y-1.5">
                    {latest.issues.map((issue, i) => (
                      <div key={i} className="rounded-md border border-line bg-base-850/60 px-3 py-2">
                        <div className="flex items-center gap-2 text-2xs">
                          <span className={cn('chip',
                            issue.severity === 'critical' ? 'border-danger/30 bg-danger/10 text-danger'
                              : issue.severity === 'major' ? 'border-warn/30 bg-warn/10 text-warn'
                                : 'border-line text-slate-400')}>{issue.severity}</span>
                          <span className="mono text-slate-500">{issue.criterion}</span>
                        </div>
                        <p className="mt-1 text-xs text-slate-400">{issue.detail}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {judges.length > 0 && (
                <div>
                  <div className="label">Judge panel</div>
                  <div className="grid gap-2 sm:grid-cols-3">
                    {judges.filter((j) => j.attempt === latest.attempt).map((j) => (
                      <div key={j.id} className="rounded-md border border-line bg-base-850/60 p-2.5">
                        <div className="flex items-center justify-between text-2xs text-slate-500">
                          <span className="mono">{j.judge_label}</span>
                          <span className={j.approved ? 'text-ok' : 'text-danger'}>
                            {j.approved ? 'pass' : 'fail'}</span>
                        </div>
                        <div className={cn('mono mt-1 text-lg', scoreTone(j.overall_score))}>
                          {j.overall_score.toFixed(1)}</div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-2 flex gap-4 text-2xs text-slate-500">
                    <span>variance {latest.variance.toFixed(2)}</span>
                    <span>agreement {(latest.agreement_rate * 100).toFixed(0)}%</span>
                  </div>
                </div>
              )}
            </div>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel title="Approval report" subtitle="Deterministic quality gate">
            {Object.keys(s.approval_report || {}).length === 0 ? <Empty title="Not yet approved" /> : (
              <div className="space-y-1">
                {Object.entries(s.approval_report).filter(([k]) => k !== 'reasons').map(([k, v]) => (
                  <div key={k} className="kv">
                    <span className="text-slate-500">{k.replace(/_/g, ' ')}</span>
                    <span className={typeof v === 'boolean' ? (v ? 'text-ok' : 'text-danger') : 'text-slate-300'}>
                      {String(v)}
                    </span>
                  </div>
                ))}
                {Array.isArray(s.approval_report.reasons) && s.approval_report.reasons.length > 0 && (
                  <ul className="mt-2 space-y-1 text-2xs text-danger">
                    {s.approval_report.reasons.map((r: string, i: number) => <li key={i}>• {r}</li>)}
                  </ul>
                )}
              </div>
            )}
          </Panel>

          <Panel title="Human review" subtitle="Approve, reject or leave feedback">
            <textarea className="input h-20 resize-y" placeholder="Reviewer feedback…"
              value={feedback} onChange={(e) => setFeedback(e.target.value)} />
            <div className="mt-2 flex gap-2">
              <button onClick={() => review('approve')} disabled={busy}
                className="btn-primary btn-sm flex-1"><Check className="h-3.5 w-3.5" /> Approve</button>
              <button onClick={() => review('reject')} disabled={busy}
                className="btn-danger btn-sm flex-1"><X className="h-3.5 w-3.5" /> Reject</button>
            </div>
            {(s.reviews || []).length > 0 && (
              <div className="mt-3 space-y-1.5">
                {(s.reviews || []).map((r) => (
                  <div key={r.id} className="rounded-md border border-line bg-base-850/60 px-2.5 py-2 text-2xs">
                    <div className="flex justify-between text-slate-500">
                      <span>{r.reviewer}</span><span>{r.decision}</span>
                    </div>
                    {r.feedback && <p className="mt-1 text-slate-400">{r.feedback}</p>}
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>

      <Panel className="mt-4" title="Refinement history"
        subtitle="Version → verdict → feedback → improved version">
        {timeline.length === 0 ? <Empty title="No versions recorded" /> : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              {timeline.map((t, i) => (
                <div key={t.version} className="flex items-center gap-2">
                  <div className={cn('rounded-lg border px-3 py-2',
                    t.outcome === 'approved' ? 'border-ok/30 bg-ok/[0.06]'
                      : t.outcome === 'rejected' ? 'border-danger/30 bg-danger/[0.06]'
                        : 'border-line bg-base-850')}>
                    <div className="text-2xs font-semibold uppercase tracking-wide text-slate-300">
                      Version {t.version}
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 text-2xs">
                      <span className="mono text-slate-500">{t.source}</span>
                      {t.score !== null && <span className={cn('mono', scoreTone(t.score))}>{t.score}</span>}
                      <span className={t.outcome === 'approved' ? 'text-ok'
                        : t.outcome === 'rejected' ? 'text-danger' : 'text-slate-500'}>{t.outcome}</span>
                    </div>
                  </div>
                  {i < timeline.length - 1 && <ArrowRight className="h-3.5 w-3.5 text-slate-600" />}
                </div>
              ))}
            </div>

            {timeline.length > 1 && (
              <>
                <div className="mt-5 flex items-center gap-2 text-xs">
                  <span className="text-slate-500">Compare</span>
                  <select className="input max-w-[110px] py-1" value={compare[0]}
                    onChange={(e) => setCompare([+e.target.value, compare[1]])}>
                    {timeline.map((t) => <option key={t.version} value={t.version}>v{t.version}</option>)}
                  </select>
                  <span className="text-slate-600">vs</span>
                  <select className="input max-w-[110px] py-1" value={compare[1]}
                    onChange={(e) => setCompare([compare[0], +e.target.value])}>
                    {timeline.map((t) => <option key={t.version} value={t.version}>v{t.version}</option>)}
                  </select>
                </div>
                <div className="mt-3 grid gap-3 lg:grid-cols-2">
                  {[left, right].map((side, i) => (
                    <div key={i} className="rounded-lg border border-line bg-base-850/40 p-3">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-slate-300">
                          Version {side?.version} · {side?.source}
                        </span>
                        {side?.score !== null && side?.score !== undefined && (
                          <span className={cn('mono text-sm', scoreTone(side.score))}>{side.score}</span>
                        )}
                      </div>
                      {side?.feedback_applied && (
                        <p className="mt-2 rounded border border-warn/20 bg-warn/5 px-2 py-1.5 text-2xs text-warn">
                          feedback applied: {side.feedback_applied}
                        </p>
                      )}
                      <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">
                        {String(side?.payload?.response ?? '')}
                      </p>
                      {side?.reasoning_summary && (
                        <p className="mt-2 border-t border-line pt-2 text-2xs text-slate-500">
                          {side.reasoning_summary}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </Panel>

      <Panel className="mt-4" title="Raw payload"><Json data={s.payload} /></Panel>
    </>
  );
}
