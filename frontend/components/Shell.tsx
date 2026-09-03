'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Activity, BarChart3, Boxes, Database, FlaskConical, GitBranch, LayoutDashboard,
  ScrollText, ShieldCheck, Sparkles, UserCheck, Workflow,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

const NAV = [
  { group: 'Overview', items: [
    { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { href: '/workflows', label: 'Workflows', icon: Workflow },
    { href: '/runs', label: 'Live Runs', icon: Activity },
  ]},
  { group: 'Data', items: [
    { href: '/samples', label: 'Samples', icon: Boxes },
    { href: '/review', label: 'Human Review', icon: UserCheck },
    { href: '/datasets', label: 'Datasets', icon: Database },
  ]},
  { group: 'Quality', items: [
    { href: '/analytics', label: 'Evaluation Analytics', icon: BarChart3 },
    { href: '/reliability', label: 'Reliability', icon: ShieldCheck },
    { href: '/traces', label: 'Traces', icon: GitBranch },
  ]},
  { group: 'Configuration', items: [
    { href: '/sops', label: 'SOP Engine', icon: ScrollText },
    { href: '/prompts', label: 'Prompt Versions', icon: Sparkles },
    { href: '/experiments', label: 'Experiments', icon: FlaskConical },
  ]},
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [health, setHealth] = useState<{ status: string; llm: string; environment: string } | null>(null);
  const [demo, setDemo] = useState(false);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.healthLlm().then((l) => setDemo(l.demo_mode)).catch(() => undefined);
  }, []);

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-base-900/60 lg:flex">
        <Link href="/" className="flex items-center gap-2.5 border-b border-line px-4 py-4">
          <div className="grid h-8 w-8 place-items-center rounded-lg border border-accent/30 bg-accent/10">
            <span className="font-mono text-xs font-bold text-accent">AE</span>
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight text-slate-100">AURA-EVAL</div>
            <div className="text-2xs text-slate-500">Evaluation Infrastructure</div>
          </div>
        </Link>

        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {NAV.map((section) => (
            <div key={section.group} className="mb-4">
              <div className="px-3 pb-1.5 text-2xs font-semibold uppercase tracking-wider text-slate-600">
                {section.group}
              </div>
              {section.items.map(({ href, label, icon: Icon }) => {
                const active = pathname === href || pathname.startsWith(`${href}/`);
                return (
                  <Link key={href} href={href}
                    className={cn(
                      'mb-0.5 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors',
                      active ? 'bg-accent/10 font-medium text-accent-soft' : 'text-slate-400 hover:bg-base-850 hover:text-slate-200',
                    )}>
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="truncate">{label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="border-t border-line p-3 text-2xs">
          <div className="flex items-center justify-between text-slate-500">
            <span>API</span>
            <span className="flex items-center gap-1.5">
              <span className={cn('h-1.5 w-1.5 rounded-full', health?.status === 'healthy' ? 'bg-ok' : 'bg-danger')} />
              {health?.status ?? 'offline'}
            </span>
          </div>
          <div className="mt-1 flex items-center justify-between text-slate-500">
            <span>Mode</span>
            <span className={demo ? 'text-warn' : 'text-ok'}>{demo ? 'demo · mock LLM' : 'live LLM'}</span>
          </div>
          <div className="mt-1 flex items-center justify-between text-slate-600">
            <span>Env</span><span>{health?.environment ?? '—'}</span>
          </div>
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-base-950/85 px-4 py-3 backdrop-blur lg:hidden">
          <Link href="/" className="font-mono text-sm font-bold text-accent">AURA-EVAL</Link>
          <nav className="flex gap-1 overflow-x-auto">
            {NAV.flatMap((s) => s.items).map(({ href, label }) => (
              <Link key={href} href={href}
                className={cn('whitespace-nowrap rounded-md px-2.5 py-1 text-xs',
                  pathname.startsWith(href) ? 'bg-accent/10 text-accent-soft' : 'text-slate-400')}>
                {label}
              </Link>
            ))}
          </nav>
        </header>
        <main className="mx-auto max-w-[1500px] p-4 sm:p-6">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({ title, description, actions }: {
  title: string; description?: string; actions?: React.ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-50">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
