import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { ProteinSignIn, useProteinSession } from './protein-account';

const URL = 'https://zoosebdmsaflxcqtyyho.supabase.co/functions/v1/protein-workbench';
const Viewer = lazy(() => import('./molstar-viewer').then(m => ({ default: m.MolstarViewer })));
type Analysis = { id: string; sequence: string; sequence_sha256: string };
type Run = { id: string; analysis_id: string; model: string; status: string; result?: { message?: string; artifact_digest?: string; scope_statement?: string; structure?: { structure_text: string; structure_format: string } } };
type History = { user_id: string; analyses: Analysis[]; runs: Run[]; remaining: number; resets_at: string; hosted_enabled: boolean };

export function ProteinWorkbench() {
  const session = useProteinSession();
  const [history, setHistory] = useState<History | null>(null);
  const [text, setText] = useState('');
  const [selected, setSelected] = useState('');
  const [model, setModel] = useState('boltz2');
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [run, setRun] = useState<Run | null>(null);
  const call = useCallback(async (body: Record<string, unknown>) => {
    if (!session) throw new Error('Sign in first.');
    const response = await fetch(URL, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${session.access_token}` }, body: JSON.stringify(body), signal: AbortSignal.timeout(110000) });
    const data = await response.json();
    if (!response.ok) throw new Error(`${data.code ?? response.status}: ${data.message ?? 'Request failed'}`);
    return data;
  }, [session]);
  const refresh = useCallback(async () => { setHistory(await call({ action: 'list' }) as History); }, [call]);
  useEffect(() => {
    setHistory(null); setRun(null); setSelected(''); setError(''); setText('');
    if (session) void refresh().catch(e => setError(e.message));
  }, [session, refresh]);
  async function perform(task: () => Promise<void>) {
    setBusy(true); setError('');
    try { await task(); } catch (e) { setError(e instanceof Error ? e.message : 'Request failed'); }
    finally { setBusy(false); }
  }
  return <section className="panel protein-workbench">
    <p className="eyebrow">PROTEIN UPLOADS · PRIVATE WORKSPACE</p><h2>Upload and inspect your protein</h2>
    <p>Paste a sequence or upload one FASTA record: 20–300 standard amino acids, up to 8 KB. Uploads are private to your account. These proteins do not receive the 1IGV stability scores.</p>
    <ProteinSignIn />
    {history && <>
      <details><summary>Your account ID</summary><code>{history.user_id}</code></details>
      <p>{history.remaining} of 2 prediction attempts remaining today · resets {history.resets_at}. Limits: 30 requests per minute per account, one active prediction per account, two predictions active across all users. Failed attempts count toward the daily prediction allowance; cached results do not consume another prediction.</p>
      {!history.hosted_enabled && <p role="status">Uploads are open. Public NVIDIA prediction is pending production-service permission and a verified credit budget. Uploading does not call a model.</p>}
      <form onSubmit={e => { e.preventDefault(); void perform(async () => {
        const data = await call({ action: 'upload', sequence: text }); setSelected(data.analysis.id); await refresh();
      }); }}>
        <label>Protein sequence or FASTA<textarea rows={5} maxLength={8192} value={text} onChange={e => setText(e.target.value)} required /></label>
        <label>FASTA file<input type="file" accept=".fasta,.fa,.faa,.txt" onChange={e => {
          const file = e.target.files?.[0]; if (!file) return;
          if (file.size > 8192) { setError('File exceeds 8 KB.'); e.target.value = ''; return; }
          void file.text().then(setText).catch(() => setError('Could not read file.'));
        }} /></label>
        <button disabled={busy || !text.trim()}>Save private protein</button>
      </form>
      <label>Saved protein<select value={selected} onChange={e => { setSelected(e.target.value); setRun(null); }}><option value="">Choose a protein</option>{history.analyses.map(a => <option key={a.id} value={a.id}>{a.id} · {a.sequence.length} residues</option>)}</select></label>
      {selected && <p>Analysis ID: <code>{selected}</code></p>}
      <label>Prediction model<select value={model} onChange={e => setModel(e.target.value)}><option value="boltz2">Boltz-2</option><option value="openfold3">OpenFold3</option></select></label>
      <label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />I have permission to send this non-confidential sequence to NVIDIA for prediction. Query-only alignment; no evolutionary MSA search.</label>
      <button disabled={busy || !selected || !consent || !history.hosted_enabled} onClick={() => void perform(async () => {
        setRun(await call({ action: 'predict', analysis_id: selected, model, provider_consent: consent })); await refresh();
      })}>{busy ? 'Working…' : `Predict uploaded protein with ${model === 'boltz2' ? 'Boltz-2' : 'OpenFold3'}`}</button>
      <button disabled={busy} onClick={() => void perform(refresh)}>Refresh history</button>
      <ul>{history.runs.map(r => <li key={r.id}><button onClick={() => void perform(async () => setRun(await call({ action: 'result', run_id: r.id })))}>{r.model} · {r.status} · {r.id}</button></li>)}</ul>
    </>}
    {error && <p role="alert">{error}</p>}
    {run && <div><h3>{run.model}: {run.status}</h3><p>Run ID: <code>{run.id}</code></p><p>{run.result?.message}</p><p>{run.result?.scope_statement}</p>
      {run.result?.structure && <Suspense fallback={<p>Loading structure…</p>}><Viewer protectedPositions={[]} buriedPositions={[]} selected={null} structureText={run.result.structure.structure_text} structureFormat={run.result.structure.structure_format} structureLabel={`${run.model} uploaded protein prediction`} /></Suspense>}
      {run.result?.artifact_digest && <p>Artifact SHA-256: <code>{run.result.artifact_digest}</code>. Recorded provenance; no verified ledger-chain claim.</p>}
    </div>}
    <p>Computational predictions only. Structure confidence and agreement do not establish folding stability, expression, binding or function.</p>
  </section>;
}
