'use client';

import { useEffect, useState } from 'react';
import { FlaskConical, History, Plus, Save, Trash2 } from 'lucide-react';
import { PageHeader } from '@/components/Shell';
import { Empty, ErrorState, Field, Json, Modal, Panel, Spinner, Stat } from '@/components/ui';
import { useAsync } from '@/hooks/useApi';
import { api } from '@/lib/api';
import { cn, fmt, scoreTone } from '@/lib/utils';
import type { SOPRule } from '@/lib/types';

const CRITERIA = ['correctness', 'relevance', 'completeness', 'instruction_following', 'safety'];
const SEVERITIES = ['minor', 'major', 'critical'] as const;

const BLANK_RULE: SOPRule = {
  id: '', text: '', criterion: 'correctness', weight: 1, severity: 'major',
};

export default function SopPage() {
  const sops = useAsync(() => api.sops(), []);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [rules, setRules] = useState<SOPRule[]>([]);
  const [threshold, setThreshold] = useState(75);
  const [changelog, setChangelog] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [testOpen, setTestOpen] = useState(false);
  const [testInput, setTestInput] = useState('Explain TCP congestion control.');
  const [testResponse, setTestResponse] = useState(
    'TCP congestion control uses AIMD: the window grows additively and halves on loss.');
  const [testResult, setTestResult] = useState<any>(null);

  const active = (sops.data || []).find((s) => s.id === activeId) || sops.data?.[0];
  const rendered = useAsync(
    () => (active ? api.renderSop(active.id) : Promise.resolve({ text: '' })), [active?.id, active?.current_version]);

  useEffect(() => {
    if (!active) return;
    const current = active.versions.find((v) => v.version === active.current_version)
      ?? active.versions[active.versions.length - 1];
    setRules((current?.rules as SOPRule[]) || []);
    setThreshold(current?.threshold ?? 75);
    setActiveId(active.id);
  }, [active?.id, active?.current_version]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save() {
    if (!active) return;
    setBusy(true);
    setMessage(null);
    try {
      await api.updateSop(active.id, { rules, threshold, changelog: changelog || 'Edited in SOP editor' });
      setChangelog('');
      await sops.refresh(true);
      await rendered.refresh(true);
      setMessage('New SOP version created.');
    } catch (e) {
      setMessage(String(e));
    } finally { setBusy(false); }
  }

  async function create() {
    setBusy(true);
    try {
      const defaults = await api.sopDefaults();
      const sop = await api.createSop({
        name: newName || 'New SOP', rules: defaults.rules, scoring: defaults.scoring,
        threshold: defaults.threshold,
      });
      setCreating(false);
      setNewName('');
      await sops.refresh(true);
      setActiveId(sop.id);
    } finally { setBusy(false); }
  }

  async function runTest() {
    if (!active) return;
    setBusy(true);
    try {
      const r = await api.testSop(active.id, [{ input: testInput, response: testResponse }]);
      setTestResult(r.results[0]);
    } finally { setBusy(false); }
  }

  if (sops.loading && !sops.data) return <Spinner label="Loading SOPs…" />;
  if (sops.error) return <ErrorState error={sops.error} onRetry={() => sops.refresh()} />;

  return (
    <>
      <PageHeader title="SOP Engine"
        description="Standard Operating Procedures drive the evaluator. Every content change creates an immutable new version."
        actions={
          <>
            <button onClick={() => setTestOpen(true)} disabled={!active} className="btn-ghost btn-sm">
              <FlaskConical className="h-3.5 w-3.5" /> Test SOP</button>
            <button onClick={() => setCreating(true)} className="btn-primary btn-sm">
              <Plus className="h-3.5 w-3.5" /> New SOP</button>
          </>
        } />

      <div className="grid gap-4 xl:grid-cols-[260px_1fr]">
        <Panel title="SOPs" bodyClass="p-0">
          {(sops.data || []).length === 0 ? <Empty title="No SOPs" /> : (
            <div>
              {(sops.data || []).map((s) => (
                <button key={s.id} onClick={() => setActiveId(s.id)}
                  className={cn('block w-full border-b border-line/40 px-3 py-2.5 text-left transition-colors',
                    active?.id === s.id ? 'bg-accent/10' : 'hover:bg-base-850')}>
                  <div className={cn('truncate text-sm', active?.id === s.id ? 'text-accent-soft' : 'text-slate-300')}>
                    {s.name}
                  </div>
                  <div className="mt-0.5 flex gap-2 text-2xs text-slate-600">
                    <span>v{s.current_version}</span>
                    <span>{s.versions.length} versions</span>
                    <span className={s.is_active ? 'text-ok' : 'text-slate-600'}>
                      {s.is_active ? 'active' : 'inactive'}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Panel>

        <div className="space-y-4">
          {!active ? <Panel><Empty title="Select an SOP" /></Panel> : (
            <>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Stat label="Current version" value={`v${active.current_version}`} />
                <Stat label="Rules" value={rules.length} />
                <Stat label="Threshold" value={threshold} tone={scoreTone(threshold)} />
                <Stat label="Status" value={active.is_active ? 'active' : 'inactive'}
                  tone={active.is_active ? 'text-ok' : 'text-slate-400'} />
              </div>

              <Panel title={`Rules · ${active.name}`}
                subtitle="Injected verbatim into the evaluator prompt at run time"
                actions={
                  <>
                    <button onClick={() => api.activateSop(active.id, !active.is_active).then(() => sops.refresh(true))}
                      className="btn-ghost btn-sm">{active.is_active ? 'Deactivate' : 'Activate'}</button>
                    <button onClick={() => setRules([...rules, { ...BLANK_RULE, id: `R${rules.length + 1}` }])}
                      className="btn-ghost btn-sm"><Plus className="h-3.5 w-3.5" /> Rule</button>
                    <button onClick={save} disabled={busy} className="btn-primary btn-sm">
                      <Save className="h-3.5 w-3.5" /> {busy ? 'Saving…' : 'Save as new version'}</button>
                  </>
                }>
                {message && <div className="mb-3 rounded-md border border-ok/25 bg-ok/5 px-3 py-2 text-xs text-ok">{message}</div>}
                <div className="space-y-2">
                  {rules.map((r, i) => (
                    <div key={i} className="grid gap-2 rounded-lg border border-line bg-base-850/50 p-3 lg:grid-cols-[70px_1fr_150px_110px_80px_40px]">
                      <input className="input py-1.5" value={r.id} placeholder="R1"
                        onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, id: e.target.value } : x))} />
                      <input className="input py-1.5" value={r.text} placeholder="The answer must…"
                        onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, text: e.target.value } : x))} />
                      <select className="input py-1.5" value={r.criterion}
                        onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, criterion: e.target.value } : x))}>
                        {CRITERIA.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                      <select className="input py-1.5" value={r.severity}
                        onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, severity: e.target.value as SOPRule['severity'] } : x))}>
                        {SEVERITIES.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                      <input type="number" step={0.1} min={0} max={10} className="input py-1.5" value={r.weight}
                        onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, weight: +e.target.value } : x))} />
                      <button onClick={() => setRules(rules.filter((_, j) => j !== i))} className="btn-ghost btn-sm px-2">
                        <Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                  ))}
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <Field label="Approval threshold (0–100)">
                    <input type="number" min={0} max={100} className="input" value={threshold}
                      onChange={(e) => setThreshold(+e.target.value)} />
                  </Field>
                  <Field label="Changelog">
                    <input className="input" value={changelog} placeholder="Why this version exists"
                      onChange={(e) => setChangelog(e.target.value)} />
                  </Field>
                </div>
              </Panel>

              <div className="grid gap-4 xl:grid-cols-2">
                <Panel title="Rendered prompt fragment" subtitle="Exactly what the evaluator receives">
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-base-950/70 p-3 font-mono text-2xs text-slate-400">
                    {rendered.data?.text || '—'}
                  </pre>
                </Panel>

                <Panel title="Version history" subtitle="Immutable SOP versions"
                  actions={<History className="h-3.5 w-3.5 text-slate-600" />} bodyClass="p-0">
                  <div className="max-h-72 overflow-y-auto">
                    {active.versions.slice().reverse().map((v) => (
                      <div key={v.id} className="flex items-center justify-between border-b border-line/40 px-3 py-2.5">
                        <div>
                          <div className="text-xs text-slate-300">
                            v{v.version} {v.version === active.current_version && (
                              <span className="chip ml-1 border-accent/30 bg-accent/10 text-accent">current</span>)}
                          </div>
                          <div className="mt-0.5 text-2xs text-slate-600">
                            {v.changelog || '—'} · threshold {v.threshold} · {(v.rules || []).length} rules
                            · {fmt.ago(v.created_at)}
                          </div>
                        </div>
                        {v.version !== active.current_version && (
                          <button className="btn-ghost btn-sm"
                            onClick={() => api.restoreSopVersion(active.id, v.version).then(() => sops.refresh(true))}>
                            Restore</button>
                        )}
                      </div>
                    ))}
                  </div>
                </Panel>
              </div>
            </>
          )}
        </div>
      </div>

      <Modal open={creating} onClose={() => setCreating(false)} title="Create SOP">
        <Field label="Name"><input className="input" value={newName} onChange={(e) => setNewName(e.target.value)}
          placeholder="Strict Research SOP" /></Field>
        <p className="mt-2 text-xs text-slate-500">Seeded with the platform default rules; edit and save to version it.</p>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={() => setCreating(false)} className="btn-ghost btn-sm">Cancel</button>
          <button onClick={create} disabled={busy} className="btn-primary btn-sm">Create</button>
        </div>
      </Modal>

      <Modal open={testOpen} onClose={() => { setTestOpen(false); setTestResult(null); }} title="Test SOP against a sample" wide>
        <div className="grid gap-3">
          <Field label="Input"><input className="input" value={testInput} onChange={(e) => setTestInput(e.target.value)} /></Field>
          <Field label="Response"><textarea className="input h-28 resize-y" value={testResponse}
            onChange={(e) => setTestResponse(e.target.value)} /></Field>
          <button onClick={runTest} disabled={busy} className="btn-primary btn-sm self-start">
            {busy ? 'Evaluating…' : 'Run evaluator'}</button>
          {testResult && (
            <div className="rounded-lg border border-line bg-base-850/60 p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-300">Verdict</span>
                <span className={cn('mono text-lg', scoreTone(testResult.overall_score))}>
                  {testResult.overall_score}</span>
              </div>
              <div className={cn('mt-1 text-xs', testResult.approved ? 'text-ok' : 'text-danger')}>
                {testResult.approved ? 'approved' : 'rejected'}
              </div>
              <Json data={testResult.evaluation} className="mt-3" />
            </div>
          )}
        </div>
      </Modal>
    </>
  );
}
