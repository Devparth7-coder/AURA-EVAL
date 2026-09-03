'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
  ArrowRight, Boxes, CheckCircle2, Database, Gauge, GitBranch, RefreshCcw,
  ScrollText, ShieldCheck, Sparkles, Workflow,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const PIPELINE = [
  { id: 'TASK', label: 'Task', detail: 'Objective + SOP', icon: ScrollText },
  { id: 'PLANNER', label: 'Planner', detail: 'Decomposes the objective', icon: Workflow },
  { id: 'GENERATOR', label: 'Generator', detail: 'Structured synthetic samples', icon: Sparkles },
  { id: 'EVALUATOR', label: 'Evaluator', detail: 'Multi-judge SOP scoring', icon: Gauge },
  { id: 'REFINER', label: 'Refiner', detail: 'Repairs rejected samples', icon: RefreshCcw },
  { id: 'APPROVAL', label: 'Approval', detail: 'Schema · dedup · threshold', icon: CheckCircle2 },
  { id: 'DATASET', label: 'Dataset', detail: 'JSON · JSONL · CSV · Parquet', icon: Database },
];

const FEATURES = [
  { icon: GitBranch, title: 'Real orchestration, not chat',
    body: 'A LangGraph state machine with conditional PASS/FAIL edges, a bounded refinement loop and durable checkpoints after every node.' },
  { icon: ShieldCheck, title: 'Reliability as a first-class metric',
    body: 'Per-agent reliability, invalid-JSON and timeout rates, retry frequency, loop-guard trips and failure-propagation chains.' },
  { icon: Gauge, title: 'Multi-judge consensus',
    body: 'Run N evaluators, measure variance and agreement, and route genuine disagreement to a human reviewer instead of guessing.' },
  { icon: Boxes, title: 'Structured, validated outputs',
    body: 'Every LLM response is parsed, schema-validated with Pydantic and repaired on failure. Raw model text is never trusted.' },
  { icon: Database, title: 'Dataset builder',
    body: 'Approved samples become instruction, chat or evaluation datasets exportable as JSON, JSONL, CSV or Parquet.' },
  { icon: Sparkles, title: 'Works with zero API keys',
    body: 'A deterministic mock provider simulates realistic agent behaviour and failures, so demos and CI are fully reproducible.' },
];

export default function Landing() {
  const [active, setActive] = useState(0);
  const [health, setHealth] = useState<'checking' | 'up' | 'down'>('checking');

  useEffect(() => {
    const t = setInterval(() => setActive((i) => (i + 1) % PIPELINE.length), 1100);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    fetch('/api/health').then((r) => setHealth(r.ok ? 'up' : 'down')).catch(() => setHealth('down'));
  }, []);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-line bg-base-950/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <div className="grid h-8 w-8 place-items-center rounded-lg border border-accent/30 bg-accent/10">
              <span className="font-mono text-xs font-bold text-accent">AE</span>
            </div>
            <span className="text-sm font-semibold tracking-tight">AURA-EVAL</span>
          </div>
          <nav className="flex items-center gap-2">
            <a href="#pipeline" className="hidden px-3 py-2 text-sm text-slate-400 hover:text-slate-200 sm:block">Pipeline</a>
            <a href="#capabilities" className="hidden px-3 py-2 text-sm text-slate-400 hover:text-slate-200 sm:block">Capabilities</a>
            <Link href="/dashboard" className="btn-primary btn-sm">Launch Evaluation</Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="grid-lines border-b border-line">
        <div className="mx-auto max-w-6xl px-5 py-20 sm:py-28">
          <div className="inline-flex items-center gap-2 rounded-full border border-line bg-base-900 px-3 py-1 text-2xs text-slate-400">
            <span className={cn('h-1.5 w-1.5 rounded-full',
              health === 'up' ? 'animate-pulse bg-ok' : health === 'down' ? 'bg-danger' : 'bg-slate-600')} />
            {health === 'up' ? 'API online · demo mode ready' : health === 'down' ? 'API offline — start the backend' : 'Checking API…'}
          </div>

          <h1 className="mt-6 max-w-3xl text-4xl font-semibold leading-[1.1] tracking-tight text-slate-50 sm:text-6xl">
            Autonomous AI Evaluation Infrastructure
          </h1>
          <p className="mt-5 max-w-2xl text-lg text-slate-400">
            Generate. Critique. Refine. Validate. Build reliable AI datasets automatically.
          </p>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-500">
            A multi-agent pipeline that turns an objective into a validated training or evaluation
            dataset — with SOP-driven scoring, bounded self-refinement, human-in-the-loop review and
            full execution traces for every agent call.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link href="/dashboard" className="btn-primary px-5 py-2.5">
              Launch Evaluation <ArrowRight className="h-4 w-4" />
            </Link>
            <Link href="/workflows" className="btn-ghost px-5 py-2.5">View Demo</Link>
          </div>

          <dl className="mt-14 grid max-w-3xl grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-4">
            {[
              ['6', 'specialised agents'],
              ['3', 'dataset styles'],
              ['4', 'export formats'],
              ['0', 'API keys required'],
            ].map(([v, l]) => (
              <div key={l} className="bg-base-900 px-4 py-4">
                <dt className="font-mono text-2xl font-semibold text-slate-100">{v}</dt>
                <dd className="mt-0.5 text-xs text-slate-500">{l}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* Animated pipeline */}
      <section id="pipeline" className="border-b border-line">
        <div className="mx-auto max-w-6xl px-5 py-16">
          <h2 className="text-lg font-semibold tracking-tight text-slate-100">The agent workflow</h2>
          <p className="mt-1 text-sm text-slate-500">
            Every stage is a durable, inspectable node. Rejected samples loop back through the refiner
            a bounded number of times — never indefinitely.
          </p>

          <div className="mt-8 flex flex-col gap-2 lg:flex-row lg:items-stretch">
            {PIPELINE.map((step, i) => {
              const Icon = step.icon;
              const isActive = i === active;
              const isDone = i < active;
              return (
                <div key={step.id} className="flex flex-1 items-center gap-2 lg:flex-col">
                  <div className={cn(
                    'w-full rounded-xl border p-3 transition-all duration-500',
                    isActive ? 'animate-pulse-ring border-accent/50 bg-accent/10'
                      : isDone ? 'border-ok/25 bg-ok/[0.04]' : 'border-line bg-base-900',
                  )}>
                    <Icon className={cn('h-4 w-4', isActive ? 'text-accent' : isDone ? 'text-ok' : 'text-slate-600')} />
                    <div className={cn('mt-2 text-xs font-semibold uppercase tracking-wide',
                      isActive ? 'text-accent-soft' : isDone ? 'text-slate-300' : 'text-slate-400')}>
                      {step.label}
                    </div>
                    <div className="mt-0.5 text-2xs leading-snug text-slate-600">{step.detail}</div>
                  </div>
                  {i < PIPELINE.length - 1 && (
                    <svg className="hidden h-3 w-full lg:block" viewBox="0 0 100 6" preserveAspectRatio="none">
                      <line x1="0" y1="3" x2="100" y2="3" stroke={isDone ? '#3ecf8e' : '#2c3648'}
                        strokeWidth="1.5" strokeDasharray="6 4"
                        className={isActive ? 'animate-flow-dash' : ''} />
                    </svg>
                  )}
                </div>
              );
            })}
          </div>

          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            {[
              ['PASS', 'Approval agent validates schema, duplicates, thresholds and SOP compliance.', 'border-ok/25 text-ok'],
              ['FAIL', 'Refinement agent reads the critique, fixes the sample and re-submits it.', 'border-warn/25 text-warn'],
              ['DISPUTED', 'Judge disagreement or a borderline score escalates to human review.', 'border-violet/25 text-violet'],
            ].map(([label, body, tone]) => (
              <div key={label} className={cn('rounded-xl border bg-base-900 p-4', tone.split(' ')[0])}>
                <div className={cn('font-mono text-2xs font-bold tracking-widest', tone.split(' ')[1])}>{label}</div>
                <p className="mt-2 text-xs leading-relaxed text-slate-400">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Capabilities */}
      <section id="capabilities" className="border-b border-line">
        <div className="mx-auto max-w-6xl px-5 py-16">
          <h2 className="text-lg font-semibold tracking-tight text-slate-100">Built like infrastructure</h2>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <div key={title} className="panel p-5 transition-colors hover:border-slate-700">
                <Icon className="h-4.5 w-4.5 text-accent" />
                <h3 className="mt-3 text-sm font-semibold text-slate-100">{title}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-500">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-10 text-xs text-slate-600">
        <span>AURA-EVAL — autonomous multi-agent evaluation & dataset generation.</span>
        <div className="flex gap-4">
          <Link href="/dashboard" className="hover:text-slate-400">Dashboard</Link>
          <a href="/api/docs" className="hover:text-slate-400">API Docs</a>
        </div>
      </footer>
    </div>
  );
}
