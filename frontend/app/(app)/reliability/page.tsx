'use client';

import { ArrowDown, ShieldAlert } from 'lucide-react';
import { PageHeader } from '@/components/Shell';
import { Bar, Empty, ErrorState, Panel, Spinner, Stat } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { cn, fmt } from '@/lib/utils';

function tone(v: number) {
  return v >= 98 ? 'text-ok' : v >= 92 ? 'text-accent' : v >= 85 ? 'text-warn' : 'text-danger';
}
function barTone(v: number) {
  return v >= 98 ? 'bg-ok' : v >= 92 ? 'bg-accent' : v >= 85 ? 'bg-warn' : 'bg-danger';
}

export default function ReliabilityPage() {
  const rel = useAsync(() => api.reliability(), [], { poll: 8000 });
  if (rel.loading && !rel.data) return <Spinner label="Computing reliability…" />;
  if (rel.error) return <ErrorState error={rel.error} onRetry={() => rel.refresh()} />;
  const r = rel.data!;

  return (
    <>
      <PageHeader title="Reliability"
        description="Agent-level reliability, error taxonomy, retry pressure and failure propagation across the pipeline." />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat label="Workflow reliability" value={fmt.pct(r.workflow_reliability)}
          tone={tone(r.workflow_reliability)} sub="completed vs terminal runs" />
        <Stat label="Retry frequency" value={r.retry_frequency.toFixed(2)} sub="avg attempts per LLM call" />
        <Stat label="Timeouts" value={r.timeouts} tone={r.timeouts ? 'text-warn' : 'text-ok'} />
        <Stat label="Invalid JSON" value={r.invalid_json_errors} tone={r.invalid_json_errors ? 'text-warn' : 'text-ok'} />
        <Stat label="Schema violations" value={r.schema_violations}
          tone={r.schema_violations ? 'text-danger' : 'text-ok'} />
        <Stat label="Loop-guard trips" value={r.loop_guard_trips}
          tone={r.loop_guard_trips ? 'text-warn' : 'text-ok'} sub="infinite loops prevented" />
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-2">
        <Panel title="Agent reliability" subtitle="Success + half-credit for degraded (recovered) calls">
          <div className="space-y-3.5">
            {r.agents.map((a) => (
              <div key={a.agent}>
                <div className="mb-1 flex items-baseline justify-between text-xs">
                  <span className="capitalize text-slate-300">{a.agent.replace(/_/g, ' ')}</span>
                  <span className={cn('mono', tone(a.reliability))}>{a.reliability.toFixed(1)}%</span>
                </div>
                <Bar value={a.reliability} tone={barTone(a.reliability)} />
                <div className="mt-1 flex gap-3 text-2xs text-slate-600">
                  <span>{a.calls} calls</span>
                  <span className="text-ok">{a.success} ok</span>
                  {a.degraded > 0 && <span className="text-warn">{a.degraded} degraded</span>}
                  {a.failed > 0 && <span className="text-danger">{a.failed} failed</span>}
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Error breakdown" subtitle="Failure taxonomy across every agent call">
          {r.error_breakdown.length === 0 ? (
            <Empty title="No errors recorded" hint="Every agent call succeeded on its first attempt." />
          ) : (
            <div className="space-y-2">
              {r.error_breakdown.map((e) => {
                const max = r.error_breakdown[0].count || 1;
                return (
                  <div key={e.error} className="rounded-lg border border-line bg-base-850/60 p-3">
                    <div className="flex items-center justify-between text-sm">
                      <span className="mono text-slate-300">{e.error}</span>
                      <span className="mono text-danger">{e.count}</span>
                    </div>
                    <div className="mt-2"><Bar value={(e.count / max) * 100} tone="bg-danger" /></div>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>
      </div>

      <Panel className="mt-4" title="Failure propagation"
        subtitle="How an upstream agent failure cascades through the pipeline">
        {r.failure_propagation.length === 0 ? (
          <Empty title="No failure cascades observed" hint="Runs completed without upstream agent failures." />
        ) : (
          <div className="space-y-4">
            {r.failure_propagation.map((f) => (
              <div key={f.run_id} className="rounded-lg border border-line bg-base-850/40 p-4">
                <div className="mb-3 flex items-center gap-2 text-xs">
                  <ShieldAlert className="h-3.5 w-3.5 text-warn" />
                  <span className="mono text-slate-400">run {f.run_id.slice(0, 8)}</span>
                  <span className="text-slate-600">·</span>
                  <span className={f.status === 'FAILED' ? 'text-danger' : 'text-slate-500'}>{f.status}</span>
                </div>
                <div className="flex flex-col gap-1">
                  {f.chain.map((step, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <div className={cn('rounded-md border px-3 py-1.5 text-xs',
                        i === 0 ? 'border-danger/30 bg-danger/[0.07] text-danger'
                          : i === f.chain.length - 1 ? 'border-warn/25 bg-warn/[0.05] text-warn'
                            : 'border-line bg-base-900 text-slate-400')}>
                        {step}
                      </div>
                      {i < f.chain.length - 1 && <ArrowDown className="h-3 w-3 text-slate-700" />}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </>
  );
}
