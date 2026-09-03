'use client';

import { useState } from 'react';
import {
  Bar as RBar, BarChart, CartesianGrid, Cell, PolarAngleAxis, PolarGrid, PolarRadiusAxis,
  Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { PageHeader } from '@/components/Shell';
import { Bar, Empty, ErrorState, Panel, Spinner, Stat } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { cn, fmt, scoreTone } from '@/lib/utils';

const AXIS = { stroke: '#4a5568', fontSize: 11 };
const TOOLTIP = {
  contentStyle: { background: '#0f131b', border: '1px solid #222a38', borderRadius: 8, fontSize: 12, color: '#e6ebf3' },
  labelStyle: { color: '#94a3b8', fontSize: 11 },
} as const;

export default function AnalyticsPage() {
  const [runId, setRunId] = useState('');
  const runs = useAsync(() => api.runs(), []);
  const ev = useAsync(() => api.evaluationAnalytics(runId || undefined), [runId], { poll: 8000 });

  if (ev.loading && !ev.data) return <Spinner label="Computing analytics…" />;
  if (ev.error) return <ErrorState error={ev.error} onRetry={() => ev.refresh()} />;

  const a = ev.data!;
  const criteria = Object.entries(a.criteria_pass_rates).map(([k, v]) => ({
    criterion: k.replace(/_/g, ' '), rate: v,
  }));

  return (
    <>
      <PageHeader title="Evaluation Analytics"
        description="Pass rates, score distribution, refinement effectiveness and which criteria cause the most failures."
        actions={
          <select className="input max-w-[240px]" value={runId} onChange={(e) => setRunId(e.target.value)}>
            <option value="">All runs</option>
            {(runs.data || []).map((r) => (
              <option key={r.id} value={r.id}>{r.id.slice(0, 8)} · {r.status.toLowerCase()}</option>
            ))}
          </select>
        } />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Pass rate" value={fmt.pct(a.pass_rate)} tone="text-ok" />
        <Stat label="Failure rate" value={fmt.pct(a.failure_rate)} tone="text-danger" />
        <Stat label="Average score" value={a.average_score.toFixed(1)} tone={scoreTone(a.average_score)}
          sub={`σ ${a.stdev_score.toFixed(2)}`} />
        <Stat label="Median score" value={a.median_score.toFixed(1)} tone={scoreTone(a.median_score)} />
        <Stat label="Avg retry count" value={a.average_retry_count.toFixed(2)}
          sub={`${a.refinement_attempts} refinements`} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Refinement success" value={fmt.pct(a.refinement_success_rate)} tone="text-ok" />
        <Stat label="Hallucination rate" value={fmt.pct(a.hallucination_rate)}
          tone={a.hallucination_rate > 20 ? 'text-danger' : 'text-warn'} />
        <Stat label="Schema failure rate" value={fmt.pct(a.schema_failure_rate)}
          tone={a.schema_failure_rate > 5 ? 'text-danger' : 'text-ok'} />
        <Stat label="Judge disagreement" value={fmt.pct(a.judge_disagreement_rate)} tone="text-violet" />
        <Stat label="Pending human review" value={a.human_review_pending} tone="text-warn" />
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-2">
        <Panel title="Criteria pass rates" subtitle="Share of evaluations scoring ≥ 8/10 per dimension">
          <div className="space-y-3">
            {criteria.map((c) => (
              <div key={c.criterion}>
                <div className="mb-1 flex justify-between text-xs">
                  <span className="capitalize text-slate-300">{c.criterion}</span>
                  <span className={cn('mono', c.rate >= 90 ? 'text-ok' : c.rate >= 75 ? 'text-accent' : 'text-warn')}>
                    {c.rate.toFixed(1)}%
                  </span>
                </div>
                <Bar value={c.rate} tone={c.rate >= 90 ? 'bg-ok' : c.rate >= 75 ? 'bg-accent' : 'bg-warn'} />
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Criteria profile" subtitle="Radar view of evaluation dimensions">
          {criteria.length === 0 ? <Empty title="No evaluations yet" /> : (
            <ResponsiveContainer width="100%" height={260}>
              <RadarChart data={criteria} outerRadius="72%">
                <PolarGrid stroke="#222a38" />
                <PolarAngleAxis dataKey="criterion" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                <PolarRadiusAxis domain={[0, 100]} tick={{ fill: '#4a5568', fontSize: 9 }} />
                <Radar dataKey="rate" stroke="#4f9cf9" fill="#4f9cf9" fillOpacity={0.22} />
                <Tooltip {...TOOLTIP} />
              </RadarChart>
            </ResponsiveContainer>
          )}
        </Panel>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Panel title="Score distribution" subtitle="Consensus scores by decile">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={a.score_distribution}>
              <CartesianGrid stroke="#1d2432" vertical={false} />
              <XAxis dataKey="bucket" tick={AXIS} axisLine={{ stroke: '#1d2432' }} tickLine={false} />
              <YAxis tick={AXIS} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip {...TOOLTIP} cursor={{ fill: 'rgba(79,156,249,0.06)' }} />
              <RBar dataKey="count" radius={[4, 4, 0, 0]}>
                {a.score_distribution.map((b, i) => (
                  <Cell key={b.bucket} fill={i >= 8 ? '#3ecf8e' : i >= 7 ? '#4f9cf9' : i >= 6 ? '#f5a623' : '#f2555a'} />
                ))}
              </RBar>
            </BarChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Top failure criteria" subtitle="Which rules cause the most rejections">
          {a.top_failure_criteria.length === 0 ? (
            <Empty title="No issues recorded" hint="Every evaluated sample passed cleanly." />
          ) : (
            <div className="space-y-2">
              {a.top_failure_criteria.map((f) => (
                <div key={f.criterion} className="rounded-lg border border-line bg-base-850/60 p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm capitalize text-slate-200">{f.criterion.replace(/_/g, ' ')}</span>
                    <span className="mono text-sm text-danger">{f.failures}</span>
                  </div>
                  <div className="mt-1.5 flex gap-3 text-2xs text-slate-500">
                    {Object.entries(f.severity_breakdown).map(([sev, n]) => (
                      <span key={sev} className={sev === 'critical' ? 'text-danger' : sev === 'major' ? 'text-warn' : ''}>
                        {sev}: {n}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
