'use client';

import Link from 'next/link';
import {
  Activity, CheckCircle2, CircleDollarSign, Clock, Database, Gauge,
  RefreshCcw, TrendingUp, XCircle,
} from 'lucide-react';
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { PageHeader } from '@/components/Shell';
import { Empty, ErrorState, Panel, Spinner, Stat, StatusChip } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { fmt, scoreTone } from '@/lib/utils';

const AXIS = { stroke: '#4a5568', fontSize: 11 };
const GRID = '#1d2432';

const TOOLTIP_STYLE = {
  contentStyle: {
    background: '#0f131b', border: '1px solid #222a38', borderRadius: 8,
    fontSize: 12, color: '#e6ebf3',
  },
  labelStyle: { color: '#94a3b8', fontSize: 11 },
} as const;

export default function DashboardPage() {
  const analytics = useAsync(() => api.analytics(), [], { poll: 5000 });
  const runs = useAsync(() => api.runs(), [], { poll: 5000 });
  const cost = useAsync(() => api.cost(), [], { poll: 10000 });

  if (analytics.loading && !analytics.data) return <Spinner label="Loading platform metrics…" />;
  if (analytics.error) return <ErrorState error={analytics.error} onRetry={() => analytics.refresh()} />;

  const s = analytics.data!.summary;
  const c = analytics.data!.charts;
  const recentRuns = (runs.data || []).slice(0, 8);

  return (
    <>
      <PageHeader
        title="Platform Dashboard"
        description="Fleet-wide view of agent workflows, dataset yield, evaluation quality and spend."
        actions={
          <>
            <Link href="/workflows" className="btn-ghost btn-sm">Workflows</Link>
            <Link href="/runs" className="btn-primary btn-sm">Live runs</Link>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Total workflows" value={fmt.num(s.total_workflows)}
          sub={`${s.total_runs} runs executed`} icon={<Activity className="h-4 w-4" />} />
        <Stat label="Running" value={fmt.num(s.running)} tone={s.running ? 'text-accent' : undefined}
          sub="in flight now" icon={<Activity className="h-4 w-4" />} />
        <Stat label="Completed" value={fmt.num(s.completed)} tone="text-ok"
          sub={`${s.stopped} stopped`} icon={<CheckCircle2 className="h-4 w-4" />} />
        <Stat label="Failed" value={fmt.num(s.failed)} tone={s.failed ? 'text-danger' : undefined}
          sub="workflow-level failures" icon={<XCircle className="h-4 w-4" />} />
        <Stat label="Datasets" value={fmt.num(s.datasets)} sub="built and stored"
          icon={<Database className="h-4 w-4" />} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Samples generated" value={fmt.num(s.samples_generated)}
          sub={`${s.samples_needs_review} awaiting review`} />
        <Stat label="Samples approved" value={fmt.num(s.samples_approved)} tone="text-ok"
          sub={s.samples_generated ? fmt.pct((s.samples_approved / s.samples_generated) * 100) + ' yield' : '—'} />
        <Stat label="Samples rejected" value={fmt.num(s.samples_rejected)}
          tone={s.samples_rejected ? 'text-danger' : undefined} sub={`${s.samples_failed} hard failures`} />
        <Stat label="Avg quality score" value={s.avg_quality_score.toFixed(1)}
          tone={scoreTone(s.avg_quality_score)} sub={`median ${s.median_quality_score.toFixed(1)}`}
          icon={<Gauge className="h-4 w-4" />} />
        <Stat label="Avg eval latency" value={fmt.ms(s.avg_evaluation_latency_ms)}
          sub={`avg retries ${s.avg_retry_count.toFixed(2)}`} icon={<Clock className="h-4 w-4" />} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Total tokens" value={fmt.tokens(s.total_tokens)}
          sub={`${fmt.tokens(s.total_input_tokens)} in · ${fmt.tokens(s.total_output_tokens)} out`} />
        <Stat label="Estimated cost" value={fmt.usd(s.total_cost_usd)}
          sub="current pricing table" icon={<CircleDollarSign className="h-4 w-4" />} />
        <Stat label="Cost / sample" value={fmt.usd(s.avg_cost_per_sample)} sub="across all runs" />
        <Stat label="Avg retry count" value={s.avg_retry_count.toFixed(2)}
          sub="refinement pressure" icon={<RefreshCcw className="h-4 w-4" />} />
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-3">
        <Panel title="Quality score distribution" subtitle="Consensus scores bucketed by decile"
          className="xl:col-span-2">
          {c.score_distribution.every((b) => !b.count) ? (
            <Empty title="No evaluations yet" hint="Run a workflow to populate the distribution." />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={c.score_distribution}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="bucket" tick={AXIS} axisLine={{ stroke: GRID }} tickLine={false} />
                <YAxis tick={AXIS} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip {...TOOLTIP_STYLE} cursor={{ fill: 'rgba(79,156,249,0.06)' }} />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {c.score_distribution.map((b, i) => (
                    <Cell key={b.bucket} fill={i >= 8 ? '#3ecf8e' : i >= 7 ? '#4f9cf9' : i >= 6 ? '#f5a623' : '#f2555a'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Panel>

        <Panel title="Pass / fail ratio" subtitle="Critic verdicts across all evaluations">
          {c.pass_fail.every((p) => !p.value) ? (
            <Empty title="No verdicts yet" />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie data={c.pass_fail} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85}
                  paddingAngle={3} stroke="#0b0e14">
                  <Cell fill="#3ecf8e" />
                  <Cell fill="#f2555a" />
                </Pie>
                <Legend wrapperStyle={{ fontSize: 12, color: '#94a3b8' }} />
                <Tooltip {...TOOLTIP_STYLE} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </Panel>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Panel title="Evaluation scores over time" subtitle="Sequential consensus scores per evaluation"
          actions={<TrendingUp className="h-4 w-4 text-slate-600" />}>
          {c.scores_over_time.length === 0 ? <Empty title="No scores recorded yet" /> : (
            <ResponsiveContainer width="100%" height={230}>
              <AreaChart data={c.scores_over_time}>
                <defs>
                  <linearGradient id="scoreFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#4f9cf9" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#4f9cf9" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="index" tick={AXIS} axisLine={{ stroke: GRID }} tickLine={false} />
                <YAxis domain={[0, 100]} tick={AXIS} axisLine={false} tickLine={false} />
                <Tooltip {...TOOLTIP_STYLE} />
                <Area type="monotone" dataKey="score" stroke="#4f9cf9" strokeWidth={2} fill="url(#scoreFill)" />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Panel>

        <Panel title="Agent execution time" subtitle="Average and p95 latency per agent">
          {c.agent_execution_time.length === 0 ? <Empty title="No agent activity yet" /> : (
            <ResponsiveContainer width="100%" height={230}>
              <BarChart data={c.agent_execution_time} layout="vertical" margin={{ left: 30 }}>
                <CartesianGrid stroke={GRID} horizontal={false} />
                <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false} unit="ms" />
                <YAxis type="category" dataKey="agent" tick={AXIS} axisLine={false} tickLine={false} width={100} />
                <Tooltip {...TOOLTIP_STYLE} cursor={{ fill: 'rgba(79,156,249,0.06)' }} />
                <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                <Bar dataKey="avg_ms" name="avg" fill="#4f9cf9" radius={[0, 3, 3, 0]} />
                <Bar dataKey="p95_ms" name="p95" fill="#a78bfa" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Panel>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Panel title="Token usage by agent" subtitle="Input vs output tokens">
          {c.token_usage.length === 0 ? <Empty title="No token usage yet" /> : (
            <ResponsiveContainer width="100%" height={230}>
              <BarChart data={c.token_usage}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="agent" tick={{ ...AXIS, fontSize: 10 }} axisLine={{ stroke: GRID }} tickLine={false} />
                <YAxis tick={AXIS} axisLine={false} tickLine={false} />
                <Tooltip {...TOOLTIP_STYLE} cursor={{ fill: 'rgba(79,156,249,0.06)' }} />
                <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                <Bar dataKey="input_tokens" name="input" stackId="t" fill="#1e3a5f" />
                <Bar dataKey="output_tokens" name="output" stackId="t" fill="#4f9cf9" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Panel>

        <Panel title="Cost estimation" subtitle="Spend attribution by model"
          actions={<span className="mono text-slate-500">{fmt.usd(cost.data?.total_cost_usd ?? 0)} total</span>}>
          {!cost.data || cost.data.by_model.length === 0 ? (
            <Empty title="No spend recorded" hint="Mock provider runs are free by design." />
          ) : (
            <div className="space-y-2">
              {cost.data.by_model.map((m) => (
                <div key={m.model} className="rounded-lg border border-line bg-base-850/60 p-3">
                  <div className="flex items-center justify-between text-sm">
                    <span className="mono text-slate-200">{m.model}</span>
                    <span className="mono text-accent">{fmt.usd(m.cost_usd)}</span>
                  </div>
                  <div className="mt-1.5 flex gap-4 text-2xs text-slate-500">
                    <span>{m.calls} calls</span>
                    <span>{fmt.tokens(m.input_tokens)} in</span>
                    <span>{fmt.tokens(m.output_tokens)} out</span>
                  </div>
                </div>
              ))}
              <div className="kv pt-2">
                <span className="text-slate-500">Average cost / sample</span>
                <span className="mono text-slate-200">{fmt.usd(cost.data.avg_cost_per_sample)}</span>
              </div>
            </div>
          )}
        </Panel>
      </div>

      <Panel className="mt-4" title="Recent runs" subtitle="Most recent workflow executions"
        actions={<Link href="/runs" className="btn-ghost btn-sm">All runs</Link>} bodyClass="p-0">
        {recentRuns.length === 0 ? (
          <Empty title="No runs yet" hint="Start a workflow to see live execution here."
            action={<Link href="/workflows" className="btn-primary btn-sm">Go to workflows</Link>} />
        ) : (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Run</th><th>Status</th><th>Generated</th><th>Approved</th>
                  <th>Rejected</th><th>Review</th><th>Tokens</th><th>Cost</th><th>Started</th><th />
                </tr>
              </thead>
              <tbody>
                {recentRuns.map((r) => (
                  <tr key={r.id}>
                    <td className="mono text-slate-400">{r.id.slice(0, 8)}</td>
                    <td><StatusChip status={r.status} /></td>
                    <td className="mono">{r.samples_generated}</td>
                    <td className="mono text-ok">{r.samples_approved}</td>
                    <td className="mono text-danger">{r.samples_rejected}</td>
                    <td className="mono text-warn">{r.samples_review}</td>
                    <td className="mono text-slate-400">{fmt.tokens(r.total_input_tokens + r.total_output_tokens)}</td>
                    <td className="mono text-slate-400">{fmt.usd(r.total_cost_usd)}</td>
                    <td className="text-2xs text-slate-500">{fmt.ago(r.started_at || r.created_at)}</td>
                    <td className="text-right">
                      <Link href={`/runs/${r.id}`} className="btn-ghost btn-sm">Inspect</Link>
                    </td>
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
