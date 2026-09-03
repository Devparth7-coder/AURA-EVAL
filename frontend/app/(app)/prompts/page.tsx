'use client';

import { useEffect, useState } from 'react';
import { GitCompare, Plus } from 'lucide-react';
import { PageHeader } from '@/components/Shell';
import { Empty, ErrorState, Field, Modal, Panel, Spinner } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { cn, fmt } from '@/lib/utils';

export default function PromptsPage() {
  const prompts = useAsync(() => api.prompts(), []);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffPair, setDiffPair] = useState<[number, number]>([1, 2]);
  const [addOpen, setAddOpen] = useState(false);
  const [draft, setDraft] = useState({ body: '', notes: '' });
  const [busy, setBusy] = useState(false);

  const active = (prompts.data || []).find((p) => p.id === activeId) || prompts.data?.[0];
  useEffect(() => { if (active) { setActiveId(active.id); setVersion(active.current_version); } },
    [active?.id, active?.current_version]); // eslint-disable-line react-hooks/exhaustive-deps

  const diff = useAsync(
    () => (active && diffOpen ? api.promptDiff(active.id, diffPair[0], diffPair[1]) : Promise.resolve({ diff: [] })),
    [active?.id, diffOpen, diffPair[0], diffPair[1]]);

  const shown = active?.versions.find((v) => v.version === version) ?? active?.versions.slice(-1)[0];

  async function addVersion() {
    if (!active) return;
    setBusy(true);
    try {
      await api.addPromptVersion(active.id, draft);
      setAddOpen(false);
      setDraft({ body: '', notes: '' });
      await prompts.refresh(true);
    } finally { setBusy(false); }
  }

  if (prompts.loading && !prompts.data) return <Spinner label="Loading prompt registry…" />;
  if (prompts.error) return <ErrorState error={prompts.error} onRetry={() => prompts.refresh()} />;

  return (
    <>
      <PageHeader title="Prompt Versions"
        description="Every agent prompt is a versioned template. Runs record the exact version used so experiments can compare them."
        actions={
          <>
            <button onClick={() => setDiffOpen(true)} disabled={!active} className="btn-ghost btn-sm">
              <GitCompare className="h-3.5 w-3.5" /> Diff</button>
            <button onClick={() => { setDraft({ body: shown?.body ?? '', notes: '' }); setAddOpen(true); }}
              disabled={!active} className="btn-primary btn-sm"><Plus className="h-3.5 w-3.5" /> New version</button>
          </>
        } />

      <div className="grid gap-4 xl:grid-cols-[240px_1fr]">
        <Panel title="Templates" bodyClass="p-0">
          {(prompts.data || []).map((p) => (
            <button key={p.id} onClick={() => { setActiveId(p.id); setVersion(p.current_version); }}
              className={cn('block w-full border-b border-line/40 px-3 py-2.5 text-left',
                active?.id === p.id ? 'bg-accent/10' : 'hover:bg-base-850')}>
              <div className={cn('text-sm', active?.id === p.id ? 'text-accent-soft' : 'text-slate-300')}>{p.key}</div>
              <div className="mt-0.5 text-2xs text-slate-600">{p.agent} · {p.versions.length} versions</div>
            </button>
          ))}
        </Panel>

        <div className="space-y-4">
          {!active ? <Panel><Empty title="No prompt selected" /></Panel> : (
            <>
              <Panel title={`${active.key} · v${shown?.version ?? '—'}`} subtitle={active.description}
                actions={
                  <select className="input max-w-[130px] py-1" value={version ?? ''}
                    onChange={(e) => setVersion(+e.target.value)}>
                    {active.versions.map((v) => (
                      <option key={v.id} value={v.version}>
                        v{v.version}{v.version === active.current_version ? ' (current)' : ''}
                      </option>
                    ))}
                  </select>
                }>
                {shown?.notes && <p className="mb-3 text-xs text-slate-500">{shown.notes}</p>}
                <pre className="max-h-[460px] overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-base-950/70 p-3 font-mono text-2xs leading-relaxed text-slate-400">
                  {shown?.body || '—'}
                </pre>
              </Panel>

              <Panel title="Version history" bodyClass="p-0">
                {active.versions.slice().reverse().map((v) => (
                  <button key={v.id} onClick={() => setVersion(v.version)}
                    className="flex w-full items-center justify-between border-b border-line/40 px-3 py-2.5 text-left hover:bg-base-850">
                    <div>
                      <span className="text-xs text-slate-300">v{v.version}</span>
                      {v.version === active.current_version && (
                        <span className="chip ml-2 border-accent/30 bg-accent/10 text-accent">current</span>)}
                      <div className="mt-0.5 text-2xs text-slate-600">{v.notes || '—'}</div>
                    </div>
                    <span className="text-2xs text-slate-600">{fmt.ago(v.created_at)}</span>
                  </button>
                ))}
              </Panel>
            </>
          )}
        </div>
      </div>

      <Modal open={diffOpen} onClose={() => setDiffOpen(false)} title="Compare prompt versions" wide>
        <div className="mb-3 flex items-center gap-2 text-xs">
          <select className="input max-w-[110px] py-1" value={diffPair[0]}
            onChange={(e) => setDiffPair([+e.target.value, diffPair[1]])}>
            {active?.versions.map((v) => <option key={v.id} value={v.version}>v{v.version}</option>)}
          </select>
          <span className="text-slate-600">vs</span>
          <select className="input max-w-[110px] py-1" value={diffPair[1]}
            onChange={(e) => setDiffPair([diffPair[0], +e.target.value])}>
            {active?.versions.map((v) => <option key={v.id} value={v.version}>v{v.version}</option>)}
          </select>
        </div>
        <pre className="max-h-[60vh] overflow-auto rounded-lg border border-line bg-base-950/70 p-3 font-mono text-2xs">
          {(diff.data?.diff || []).length === 0 ? <span className="text-slate-600">No differences.</span> :
            (diff.data?.diff || []).map((line, i) => (
              <div key={i} className={line.startsWith('+') ? 'text-ok' : line.startsWith('-') ? 'text-danger'
                : line.startsWith('@') ? 'text-accent' : 'text-slate-500'}>{line}</div>
            ))}
        </pre>
      </Modal>

      <Modal open={addOpen} onClose={() => setAddOpen(false)} title="Create prompt version" wide>
        <Field label="Notes"><input className="input" value={draft.notes}
          onChange={(e) => setDraft({ ...draft, notes: e.target.value })} placeholder="What changed and why" /></Field>
        <div className="mt-3">
          <Field label="Prompt body">
            <textarea className="input h-72 resize-y font-mono text-xs" value={draft.body}
              onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
          </Field>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={() => setAddOpen(false)} className="btn-ghost btn-sm">Cancel</button>
          <button onClick={addVersion} disabled={busy || draft.body.length < 10} className="btn-primary btn-sm">
            {busy ? 'Saving…' : 'Create version'}</button>
        </div>
      </Modal>
    </>
  );
}
