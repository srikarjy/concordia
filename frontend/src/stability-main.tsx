import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createPluginUI } from 'molstar/lib/mol-plugin-ui/index.js';
import { renderReact18 } from 'molstar/lib/mol-plugin-ui/react18.js';
import { DefaultPluginUISpec } from 'molstar/lib/mol-plugin-ui/spec.js';
import { MolScriptBuilder as MS } from 'molstar/lib/mol-script/language/builder.js';
import { ColorNames } from 'molstar/lib/mol-util/color/names.js';
import 'molstar/lib/mol-plugin-ui/skin/light.scss';
import './stability.css';

type Candidate = {
  candidate: { variant_id: string; position: number; mutant_aa: string };
  rank: number;
  mean_prediction_ddg_kcal_higher_is_more_stable: number;
  ensemble_sigma: number;
  interval_90_kcal_mol?: { lower: number; upper: number; width: number };
  soft_flags?: Array<{ trigger: string; evidence: unknown }>;
};
type Refusal = { candidate: { variant_id: string }; trigger: string; evidence: unknown };
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

function MolstarViewer({ report, selected }: { report: Report; selected: number | null }) {
  const target = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState('Loading AlphaFold structure…');
  useEffect(() => {
    let disposed = false;
    void (async () => {
      if (!target.current) return;
      const plugin = await createPluginUI({ target: target.current, render: renderReact18, spec: DefaultPluginUISpec() });
      const pdb = await fetch('/data/structure/1IGV.pdb').then((response) => response.text());
      const data = await plugin.builders.data.rawData({ data: pdb, label: '1IGV AlphaFold model' });
      const trajectory = await plugin.builders.structure.parseTrajectory(data, 'pdb');
      const preset = await plugin.builders.structure.hierarchy.applyPreset(trajectory, 'default');
      const structure = preset?.structure;
      if (structure) {
        const protectedPositions = report.structure.protected_residues.map((item) => item.local_position);
        const buriedPositions = report.structure.soft_buried_positions;
        const protectedComponent = await plugin.builders.structure.tryCreateComponentFromExpression(
          structure,
          MS.struct.generator.atomGroups({ 'residue-test': MS.core.set.has([MS.set(...protectedPositions), MS.ammp('auth_seq_id')]) }),
          'hard-protected',
          { label: 'Hard-protected UniProt sites' },
        );
        if (protectedComponent) await plugin.builders.structure.representation.addRepresentation(protectedComponent, { type: 'ball-and-stick', color: 'uniform', colorParams: { value: ColorNames.red } });
        const buriedComponent = await plugin.builders.structure.tryCreateComponentFromExpression(
          structure,
          MS.struct.generator.atomGroups({ 'residue-test': MS.core.set.has([MS.set(...buriedPositions), MS.ammp('auth_seq_id')]) }),
          'soft-buried',
          { label: 'Soft buried-core positions' },
        );
        if (buriedComponent) await plugin.builders.structure.representation.addRepresentation(buriedComponent, { type: 'ball-and-stick', color: 'uniform', colorParams: { value: ColorNames.gold } });
      }
      if (!disposed) setStatus('Loaded · neutral coloring; pLDDT coloring off');
    })().catch(() => setStatus('Structure viewer failed to load'));
    return () => { disposed = true; };
  }, []);
  return <div className="viewer-wrap"><div className="viewer-status">{status}{selected ? ` · selected position ${selected}` : ''}</div><div ref={target} className="molstar" /></div>;
}

function App() {
  const [report, setReport] = useState<Report | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => { void fetch('/data/stability.json').then((r) => r.json()).then(setReport); }, []);
  if (!report) return <main className="page"><p>Loading precomputed result…</p></main>;
  return <main className="page">
    <header><p className="eyebrow">CONCORDIA / STATIC EVIDENCE VIEW</p><h1>Measured stability, with refusals in the open.</h1><p className="scope">{report.scope_statement}</p></header>
    <section className="grid two"><article className="panel"><h2>Ranked candidates</h2><p className="muted">Production ranker: ThermoMPNN + one-hot rank average. Sigma is refusal-only.</p><table><thead><tr><th>Rank</th><th>Mutation</th><th>Predicted ΔΔG</th><th>90% interval</th></tr></thead><tbody>{report.candidates.map((item) => <tr key={item.candidate.variant_id} onClick={() => setSelected(item.candidate.position)} className={selected === item.candidate.position ? 'selected' : ''}><td>{item.rank}</td><td>{item.candidate.variant_id}</td><td>{item.mean_prediction_ddg_kcal_higher_is_more_stable.toFixed(4)} kcal/mol</td><td>{item.interval_90_kcal_mol ? `${item.interval_90_kcal_mol.lower.toFixed(2)} to ${item.interval_90_kcal_mol.upper.toFixed(2)}` : '—'}</td></tr>)}</tbody></table></article><article className="panel"><h2>Structure</h2><p className="muted">{report.structure.source}. pLDDT coloring: off.</p><MolstarViewer report={report} selected={selected} /><div className="legend"><span><i className="hard" /> hard-protected UniProt site</span><span><i className="soft" /> soft buried-core flag</span><span><i className="neutral" /> neutral structure</span></div></article></section>
    <section className="grid two"><article className="panel"><h2>Refusals</h2>{report.refusals.length ? report.refusals.map((item) => <div className="refusal" key={item.candidate.variant_id}><strong>{item.candidate.variant_id}</strong><span>{item.trigger}</span><code>{JSON.stringify(item.evidence)}</code></div>) : <p>None in this artifact.</p>}</article><article className="panel"><h2>Soft flags</h2><p>Buried positions (RSA &lt; 0.15): {report.structure.soft_buried_positions.join(', ') || 'none recorded'}.</p><p>Unseen positions are soft flags and are not hard refusals.</p><p>Interval PICP: {(report.interval_context.holdout_picp * 100).toFixed(1)}%; mean width: {report.interval_context.mean_width_kcal_mol.toFixed(2)} kcal/mol; label range: {report.interval_context.label_range_kcal_mol.join(' to ')}.</p></article></section>
    <section className="panel provenance"><h2>What this means</h2><p>{report.scope_statement}</p><p>Artifact digest: <code>{report.artifact_digest}</code></p><p>Rank-average recall: modulo {report.scope_metrics.thermompnn_rank_average_top10_recall_modulo}; contiguous {report.scope_metrics.thermompnn_rank_average_top10_recall_contiguous}.</p></section>
  </main>;
}

createRoot(document.getElementById('root')!).render(<App />);
