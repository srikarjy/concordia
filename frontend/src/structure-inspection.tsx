import { lazy, Suspense, useState } from 'react';
import { supabase, useProteinSession } from './protein-account';

const GATEWAY = 'https://zoosebdmsaflxcqtyyho.supabase.co/functions/v1/structure-gateway';
const Viewer = lazy(() => import('./molstar-viewer.js').then((module) => ({ default: module.MolstarViewer })));

type StructureResult = {
  status: string;
  operation?: 'boltz2' | 'openfold3';
  message?: string;
  selected_mutation: string;
  artifact_digest: string;
  ledger_intact: boolean;
  scope_statement: string;
  structure: null | {
    structure_text: string;
    structure_format: string;
  };
  model?: string;
  provider_latency_ms?: number;
  provider_response_digest?: string;
  input_sequence_hash?: string;
  limitations?: string[];
};

export function StructureInspection({ mutations, candidate, protectedPositions }: {
  mutations: string[];
  candidate: { variant_id: string; position: number } | null;
  protectedPositions: number[];
}) {
  const [accessToken, setAccessToken] = useState('');
  const session = useProteinSession();
  const [email, setEmail] = useState('');
  const [loginMessage, setLoginMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<StructureResult | null>(null);
  const [operation, setOperation] = useState<'boltz2' | 'openfold3'>('boltz2');
  const [error, setError] = useState<string | null>(null);
  const mutation = candidate?.variant_id.replace(/^1IGV\.pdb_/, '');

  async function requestLogin() {
    if (!email.trim()) return;
    setLoginMessage(null);
    const { error: loginError } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      options: { emailRedirectTo: window.location.origin + window.location.pathname },
    });
    setLoginMessage(loginError ? loginError.message : 'Check your email for the owner sign-in link.');
  }

  async function inspect() {
    const bearer = accessToken.trim() || session?.access_token;
    if (!mutation || !bearer || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await fetch(GATEWAY, {
        method: 'POST',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${bearer}` },
        body: JSON.stringify({ operation, domain: '1IGV', mutations, selected_mutation: mutation }),
        signal: AbortSignal.timeout(600_000),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.message === 'string' ? `${data.code ?? response.status}: ${data.message}` : typeof data.detail === 'string' ? data.detail : 'Structure inspection was rejected.');
      setResult({ ...data, selected_mutation: data.selected_mutation ?? mutation, operation: data.operation ?? operation } as StructureResult);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Structure inspection is unavailable.');
    } finally {
      setBusy(false);
    }
  }

  return <section className="panel structure-inspection">
    <p className="eyebrow">THERMOMPNN → CONSTRAINT CHECK → NVIDIA STRUCTURE MODEL</p>
    <h2>Inspect an accepted candidate’s structure</h2>
    <p>Scoring does not automatically refold single mutations. This separate owner-authenticated action predicts a structure for the selected accepted candidate; it does not change its stability score or rank.</p>
    <p>Selected: <strong>{mutation ?? 'Select a ranked candidate above'}</strong>. The server rechecks the constraint decision before calling NVIDIA. Refused candidates cannot use this action.</p>
    <div className="score-form">
      {!session ? <>
        <label htmlFor="structure-email">Owner sign-in email</label>
        <div className="score-controls"><input id="structure-email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="owner email" />
          <button type="button" onClick={() => void requestLogin()} disabled={!email.trim()}>Email sign-in link</button>
        </div>
        {loginMessage && <p className="muted" role="status">{loginMessage}</p>}
      </> : <p className="muted">Signed in as {session.user.email ?? 'owner'} · <button type="button" className="inline-button" onClick={() => void supabase.auth.signOut()}>Sign out</button></p>}
      <label htmlFor="structure-token">Optional Supabase access token override</label>
      <div className="score-controls"><input id="structure-token" type="password" autoComplete="off" value={accessToken} onChange={(event) => setAccessToken(event.target.value)} placeholder={session ? 'Using signed-in owner session' : 'Paste a session token'} />
        <select aria-label="Structure model" value={operation} onChange={(event) => setOperation(event.target.value as 'boltz2' | 'openfold3')} disabled={busy}><option value="boltz2">Boltz-2</option><option value="openfold3">OpenFold3 comparison</option></select>
        <button type="button" onClick={() => void inspect()} disabled={busy || !mutation || !(accessToken.trim() || session)}>{busy ? 'Checking constraints and predicting…' : `Predict with ${operation === 'boltz2' ? 'Boltz-2' : 'OpenFold3'}`}</button>
        <button className="secondary-button" type="button" onClick={() => setAccessToken('')}>Clear token</button>
      </div>
    </div>
    <p className="muted">The access token is kept only in this tab’s memory. Your NVIDIA key stays in Supabase Vault. Cached structures are reused; the gateway permits three uncached calls per day. Please wait for the result before retrying.</p>
    {busy && <p role="status">ThermoMPNN checks the candidate, then {operation === 'boltz2' ? 'Boltz-2' : 'OpenFold3'} runs through NVIDIA. This can take several minutes.</p>}
    {error && <p role="alert" className="error-message">{error}</p>}
    {result && result.selected_mutation === mutation && result.operation === operation && <div className="inspection-result" role="status">
      <h3>{result.selected_mutation}: {result.status}</h3>
      {result.message && <p>{result.message}</p>}
      <p>{result.scope_statement}</p>
      {result.structure && <>
        <p>Model: {result.model ?? result.operation} · Recorded provider latency: {((result.provider_latency_ms ?? 0) / 1000).toFixed(2)} s (a cached result retains its original latency).</p>
        <Suspense fallback={<p>Loading predicted structure…</p>}><Viewer
          protectedPositions={protectedPositions} buriedPositions={[]} selected={null}
          structureText={result.structure.structure_text}
          structureFormat={result.structure.structure_format}
          structureLabel={`${result.model ?? result.operation} prediction: ${result.selected_mutation}`}
        /></Suspense>
        <details><summary>Structure provenance and limits</summary><p>Sequence SHA-256: <code>{result.input_sequence_hash}</code></p><p>Provider response SHA-256: <code>{result.provider_response_digest}</code></p><ul>{(result.limitations ?? []).map((limit) => <li key={limit}>{limit}</li>)}</ul></details>
      </>}
      <p>Combined artifact: <code>{result.artifact_digest}</code> · Ledger chain: {result.ledger_intact ? 'verified' : 'not verified'}.</p>
      <button type="button" className="secondary-button" onClick={() => {
        const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }));
        const link = document.createElement('a'); link.href = url; link.download = `concordia-${result.selected_mutation}.json`; link.click(); URL.revokeObjectURL(url);
      }}>Download combined result</button>
    </div>}
  </section>;
}
