'use client';

import { AlertTriangle, Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn, STATUS_TONE } from '@/lib/utils';

export function Panel({ title, subtitle, actions, children, className, bodyClass }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode;
  children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={cn('panel animate-fade-up', className)}>
      {(title || actions) && (
        <header className="panel-head">
          <div className="min-w-0">
            {title && <h3 className="truncate text-sm font-semibold text-slate-100">{title}</h3>}
            {subtitle && <p className="mt-0.5 truncate text-xs text-slate-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn('p-4', bodyClass)}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, tone, icon }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: string; icon?: ReactNode;
}) {
  return (
    <div className="panel p-4 transition-colors hover:border-slate-700">
      <div className="flex items-center justify-between">
        <span className="text-2xs font-medium uppercase tracking-wider text-slate-500">{label}</span>
        {icon && <span className="text-slate-600">{icon}</span>}
      </div>
      <div className={cn('mt-2 font-mono text-2xl font-semibold tracking-tight', tone || 'text-slate-100')}>
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

export function StatusChip({ status, className }: { status: string; className?: string }) {
  return (
    <span className={cn('chip', STATUS_TONE[status] || 'border-line bg-base-800 text-slate-400', className)}>
      {status === 'RUNNING' && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}
      {status.replace(/_/g, ' ').toLowerCase()}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
      <Loader2 className="h-4 w-4 animate-spin" />
      {label || 'Loading…'}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: { code?: string; message: string }; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-danger/25 bg-danger/5 p-6 text-center">
      <AlertTriangle className="h-5 w-5 text-danger" />
      <div>
        <p className="text-sm font-medium text-slate-200">{error.code || 'Error'}</p>
        <p className="mt-1 text-xs text-slate-400">{error.message}</p>
      </div>
      {onRetry && <button onClick={onRetry} className="btn-ghost btn-sm">Retry</button>}
    </div>
  );
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 py-12 text-center">
      <p className="text-sm font-medium text-slate-300">{title}</p>
      {hint && <p className="max-w-sm text-xs text-slate-500">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function Bar({ value, max = 100, tone = 'bg-accent' }: { value: number; max?: number; tone?: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-base-800">
      <div className={cn('h-full rounded-full transition-all duration-500', tone)} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
      {hint && <p className="mt-1 text-2xs text-slate-600">{hint}</p>}
    </div>
  );
}

export function Json({ data, className }: { data: unknown; className?: string }) {
  return (
    <pre className={cn('max-h-72 overflow-auto rounded-lg border border-line bg-base-950/70 p-3 font-mono text-2xs leading-relaxed text-slate-400', className)}>
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export function Modal({ open, onClose, title, children, wide }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm sm:p-8">
      <div className={cn('panel w-full animate-fade-up', wide ? 'max-w-4xl' : 'max-w-xl')}>
        <header className="panel-head">
          <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
          <button onClick={onClose} className="btn-ghost btn-sm">Close</button>
        </header>
        <div className="max-h-[75vh] overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}
