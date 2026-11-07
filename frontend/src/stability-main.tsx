import { FormEvent, lazy, Suspense, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { StructureInspection } from './structure-inspection';
import { ProteinWorkbench } from './protein-workbench';
import './stability.css';

const STABILITY_ARTIFACT = '/data/dae4e417463b959e68b7ab2f25d4475e46e0be8d63d7af4c9c42bf1e78540b00.json';
const STABILITY_API = import.meta.env.VITE_STABILITY_API_ROOT ?? (['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname) ? '/api/stability' : 'https://srikarjy025-concordia-thermompnn.hf.space');

type Candidate = {
  candidate: { variant_id: string; position: number; mutant?: string; mutant_aa?: string };
  rank: number;
  mean_prediction_ddg_kcal_higher_is_more_stable: number;
  ensemble_sigma: number;
  interval_90_kcal_mol?: { lower: number; upper: number; width: number };
  soft_flags?: Array<{ code?: string; trigger?: string; evidence?: unknown; rsa?: number; cutoff?: number }>;
};
type Refusal = { variant_id: string; refused: boolean; triggers: Array<Record<string, unknown>> };
type Report = {
  artifact_digest: string;
  domain_id: string;
  property: string;
  candidates: Candidate[];
  refusals: Refusal[];
  scope_statement: string;
  interval_context: { holdout_picp: number; mean_width_kcal_mol: number; range_fraction: number; label_range_kcal_mol: number[]; ranking_use: string };
  scope_metrics: Record<string, string>;
  structure: { path: string; source: string; protected_residues: Array<{ local_position: number; feature_type: string; accession: string }>; soft_buried_positions: number[] };
};
const MolstarViewer = lazy(() => import('./molstar-viewer.js').then((module) => ({ default: module.MolstarViewer })));

function IntervalBand({ item, range }: { item: Candidate; range: number[] }) {
  const [min, max] = range;
  const width = 240;
  const scale = (value: number) => Math.max(0, Math.min(width, ((value - min) / (max - min)) * width));
  const interval = item.interval_90_kcal_mol;
  if (!interval) return <span>—</span>;
  return <div className="interval-band" title="Calibrated 90% interval; too wide to rank confidently">
    <svg viewBox={`0 0 ${width} 30`} role="img" aria-label={`90% interval from ${interval.lower.toFixed(2)} to ${interval.upper.toFixed(2)} kilocalories per mole`}>
      <rect x="0" y="12" width={width} height="6" rx="3" className="interval-track" />
      <rect x={scale(interval.lower)} y="8" width={Math.max(2, scale(interval.upper) - scale(interval.lower))} height="14" rx="7" className="interval-fill" />
      <line x1={scale(0)} x2={scale(0)} y1="4" y2="26" className="interval-zero" />
      <line x1={scale(item.mean_prediction_ddg_kcal_higher_is_more_stable)} x2={scale(item.mean_prediction_ddg_kcal_higher_is_more_stable)} y1="5" y2="25" className="interval-point" />
    </svg>
    <span>{interval.lower.toFixed(2)} to {interval.upper.toFixed(2)}</span>
  </div>;
}

function refusalPosition(item: Refusal): number | null {
  for (const trigger of item.triggers) {
    const value = trigger.position ?? trigger.local_position;
    if (typeof value === 'number') return value;
    const evidence = trigger.evidence;
    if (typeof evidence === 'object' && evidence !== null && 'position' in evidence) {
      const position = (evidence as { position?: unknown }).position;
      if (typeof position === 'number') return position;
    }
  }
  const match = item.variant_id.match(/(?:_|:)([A-Z])?(\d+)/);
  return match ? Number(match[2]) : null;
}

function errorMessage(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'object' && value !== null && 'detail' in value) return errorMessage((value as { detail?: unknown }).detail);
  if (typeof value === 'object' && value !== null && 'triggers' in value) {
    const triggers = (value as { triggers?: unknown }).triggers;
    if (Array.isArray(triggers)) return triggers.map((trigger) => {
      if (typeof trigger !== 'object' || trigger === null) return String(trigger);
      const item = trigger as { code?: unknown; position?: unknown; evidence?: unknown };
      return [item.code, item.position === undefined ? null : `position ${item.position}`, item.evidence].filter(Boolean).join(': ');
    }).join('; ');
  }
  return 'The scoring service did not accept this request.';
}

function App() {
  const [report, setReport] = useState<Report | null>(null);
  const [savedReport, setSavedReport] = useState<Report | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mutationText, setMutationText] = useState('A13Q,K6Q,L52Y');
  const [isScoring, setIsScoring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLive, setIsLive] = useState(false);
  useEffect(() => {
    void fetch(STABILITY_ARTIFACT).then((r) => { if (!r.ok) throw new Error('Saved evidence unavailable'); return r.json(); }).then((nextReport: Report) => { setReport(nextReport); setSavedReport(nextReport); }).catch(() => setError('The saved evidence could not be loaded.'));
  }, []);
  async function scoreMutations(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const mutations = mutationText.split(',').map((item) => item.trim()).filter(Boolean);
    if (!mutations.length) {
      setError('Enter at least one mutation, such as A13Q or A13Q:K6Q.');
      return;
    }
    setIsScoring(true);
    setError(null);
    try {
      const response = await fetch(`${STABILITY_API}/score`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ domain: '1IGV', mutations }),
        signal: AbortSignal.timeout(120_000),
      });
      const payload: unknown = await response.json();
      if (!response.ok) throw new Error(errorMessage(payload));
      setReport(payload as Report);
      setSelectedId(null);
      setIsLive(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The scoring service is unavailable.');
    } finally {
      setIsScoring(false);
    }
  }
  function showSavedExample() {
    if (!savedReport) return;
    setReport(savedReport);
    setSelectedId(null);
    setError(null);
    setIsLive(false);
  }
  if (!report) return <main className="page">{error ? <p role="alert">{error} Reload the page to try again.</p> : <p>Loading precomputed result…</p>}</main>;
  const selectedCandidate = selectedId === null ? report.candidates[0] : report.candidates.find((item) => item.candidate.variant_id === selectedId);
  const selectedRefusal = report.refusals.find((item) => item.variant_id === selectedId);
  const selected = selectedId === null ? null : selectedCandidate?.candidate.position ?? (selectedRefusal ? refusalPosition(selectedRefusal) : null);
  const displayedMutations = [...report.candidates.map((item) => item.candidate.variant_id), ...report.refusals.map((item) => item.variant_id)].map((id) => id.replace(/^1IGV\.pdb_/, '')).join(', ');
  return <main className="page">
    <header><a href="/">← Variant review workspace</a><p className="eyebrow">CONCORDIA / MEASURED STABILITY VIEW</p><h1>Stability predictions checked against measured data.</h1><p className="scope">{report.scope_statement}</p></header>
    <ProteinWorkbench />
    <section className="panel request-panel"><div><p className="eyebrow">LIVE MEASURED-STABILITY REQUEST</p><h2>Score mutations on 1IGV</h2><p className="muted">Enter comma-separated candidates. Use a colon for a multi-mutant, for example <code>A13Q:K6Q</code>.</p></div><form onSubmit={scoreMutations} className="score-form"><label htmlFor="mutations">Mutations</label><div className="score-controls"><input id="mutations" value={mutationText} onChange={(event) => setMutationText(event.target.value)} placeholder="A13Q,K6Q,L52Y" disabled={isScoring} /><button type="submit" disabled={isScoring}>{isScoring ? 'Scoring…' : 'Score mutations'}</button><button type="button" className="secondary-button" onClick={showSavedExample} disabled={isScoring}>View saved example</button></div></form><p className="live-status" role="status">{isLive ? 'Showing the last completed scoring result' : 'Showing a saved example, not the mutations currently entered above'}. Displayed candidates: {displayedMutations}. {isScoring && 'Scoring the new request; previous results remain visible.'}</p>{error && <p className="error-message" role="alert">{error}</p>}</section>
    <section className="grid two"><article className="panel"><h2>Ranked candidates</h2><p className="muted">Benchmark ranker: ThermoMPNN + one-hot rank average. The displayed ΔΔG and intervals come from a separate ensemble, so rank need not follow the displayed ΔΔG. Uncertainty is not a ranking term.</p><p className="chart-note">Positive ΔΔG means more stable relative to the reference in this dataset’s convention; values are predictions, not new measurements. Every band uses the full observed ΔΔG range ({report.interval_context.label_range_kcal_mol.join(' to ')} kcal/mol); zero is the solid line.</p>{report.candidates.length ? <table><thead><tr><th>Rank</th><th>Mutation</th><th>Predicted ΔΔG</th><th>90% interval</th></tr></thead><tbody>{report.candidates.map((item) => <tr key={item.candidate.variant_id} onClick={() => setSelectedId(item.candidate.variant_id)} className={selectedId === item.candidate.variant_id ? 'selected' : ''}><td>{item.rank}</td><td>{item.candidate.variant_id}</td><td>{item.mean_prediction_ddg_kcal_higher_is_more_stable.toFixed(4)} kcal/mol</td><td><IntervalBand item={item} range={report.interval_context.label_range_kcal_mol} /></td></tr>)}</tbody></table> : <p>No candidates were ranked.</p>}</article><article className="panel"><h2>Structure</h2><p className="muted">{report.structure.source}. Categorical coloring only; pLDDT coloring is off.</p><Suspense fallback={<div className="viewer-wrap"><p className="viewer-status">Loading structure viewer…</p></div>}><MolstarViewer protectedPositions={report.structure.protected_residues.map((item) => item.local_position)} buriedPositions={report.structure.soft_buried_positions} selected={selected} /></Suspense><div className="legend"><span><i className="hard" /> hard-protected UniProt site</span><span><i className="soft" /> soft buried-core flag</span><span><i className="neutral" /> neutral structure</span></div></article></section>
    <section className="grid two"><article className="panel"><h2>Refusals</h2>{report.refusals.length ? report.refusals.map((item) => { return <button className={`refusal ${selectedId === item.variant_id ? 'selected-refusal' : ''}`} key={item.variant_id} onClick={() => setSelectedId(item.variant_id)}><strong>{item.variant_id}</strong><span>{item.triggers.map((trigger) => String(trigger.code ?? 'refused')).join(', ')}</span><code>{JSON.stringify(item.triggers)}</code></button>; }) : <p>None in this request.</p>}</article><article className="panel"><h2>Soft flags</h2><p>Buried positions (RSA &lt; 0.15): {report.structure.soft_buried_positions.join(', ') || 'none recorded'}.</p><p>Unseen positions are soft flags and are not hard refusals.</p><p>Held-out benchmark interval coverage (PICP): {(report.interval_context.holdout_picp * 100).toFixed(1)}%; held-out mean width: {report.interval_context.mean_width_kcal_mol.toFixed(2)} kcal/mol; label range: {report.interval_context.label_range_kcal_mol.join(' to ')}.</p></article></section>
    <StructureInspection
      mutations={[...report.candidates.map((item) => item.candidate.variant_id), ...report.refusals.map((item) => item.variant_id)].map((id) => id.replace(/^1IGV\.pdb_/, ''))}
      candidate={selectedCandidate?.candidate ?? null}
      protectedPositions={report.structure.protected_residues.map((item) => item.local_position)}
    />
    <section className="panel provenance"><h2>What this means</h2><p>{report.scope_statement}</p><p>Artifact digest: <code>{report.artifact_digest}</code></p><p>Rank-average recall: modulo {report.scope_metrics.thermompnn_rank_average_top10_recall_modulo}; contiguous {report.scope_metrics.thermompnn_rank_average_top10_recall_contiguous}.</p></section>
  </main>;
}

createRoot(document.getElementById('root')!).render(<App />);
