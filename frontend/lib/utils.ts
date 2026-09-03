import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const fmt = {
  num: (n: number | null | undefined, digits = 0) =>
    n === null || n === undefined || Number.isNaN(n) ? '—' : n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits > 0 ? Math.min(digits, 2) : 0 }),
  pct: (n: number | null | undefined, digits = 1) =>
    n === null || n === undefined ? '—' : `${n.toFixed(digits)}%`,
  usd: (n: number | null | undefined) => {
    if (n === null || n === undefined) return '—';
    if (n === 0) return '$0.00';
    if (n < 0.01) return `$${n.toFixed(5)}`;
    return `$${n.toFixed(2)}`;
  },
  ms: (n: number | null | undefined) => {
    if (n === null || n === undefined) return '—';
    return n < 1000 ? `${Math.round(n)}ms` : `${(n / 1000).toFixed(2)}s`;
  },
  tokens: (n: number | null | undefined) => {
    if (!n) return '0';
    return n >= 1_000_000 ? `${(n / 1e6).toFixed(2)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
  },
  bytes: (n: number) => (n < 1024 ? `${n} B` : n < 1024 ** 2 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 ** 2).toFixed(2)} MB`),
  time: (iso: string | null | undefined) => {
    if (!iso) return '—';
    const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
    return d.toLocaleTimeString(undefined, { hour12: false });
  },
  date: (iso: string | null | undefined) => {
    if (!iso) return '—';
    const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
    return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  },
  ago: (iso: string | null | undefined) => {
    if (!iso) return '—';
    const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`).getTime();
    const s = Math.max(0, (Date.now() - d) / 1000);
    if (s < 60) return `${Math.floor(s)}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  },
};

export const STATUS_TONE: Record<string, string> = {
  COMPLETED: 'text-ok border-ok/30 bg-ok/10',
  RUNNING: 'text-accent border-accent/30 bg-accent/10',
  PENDING: 'text-slate-300 border-line bg-base-800',
  PAUSED: 'text-warn border-warn/30 bg-warn/10',
  FAILED: 'text-danger border-danger/30 bg-danger/10',
  STOPPED: 'text-warn border-warn/30 bg-warn/10',
  AUTO_APPROVED: 'text-ok border-ok/30 bg-ok/10',
  HUMAN_APPROVED: 'text-ok border-ok/30 bg-ok/10',
  AUTO_REJECTED: 'text-danger border-danger/30 bg-danger/10',
  HUMAN_REJECTED: 'text-danger border-danger/30 bg-danger/10',
  NEEDS_REVIEW: 'text-warn border-warn/30 bg-warn/10',
  IN_PROGRESS: 'text-accent border-accent/30 bg-accent/10',
  SUCCESS: 'text-ok border-ok/30 bg-ok/10',
  DEGRADED: 'text-warn border-warn/30 bg-warn/10',
  IDLE: 'text-slate-400 border-line bg-base-800',
};

export function scoreTone(score: number | null | undefined) {
  if (score === null || score === undefined) return 'text-slate-400';
  if (score >= 85) return 'text-ok';
  if (score >= 70) return 'text-accent';
  if (score >= 55) return 'text-warn';
  return 'text-danger';
}
