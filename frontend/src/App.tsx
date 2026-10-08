import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, ArrowRight, Atom, Box, CheckCircle2, ChevronRight, CircleHelp, Dna,
  FlaskConical, GitBranch, Loader2, Network, Pause, Play, RotateCcw, Search,
  ShieldCheck, Sparkles, Upload, Wand2, XCircle,
} from 'lucide-react';
import { EvidenceGraph } from './Graph';
import type {
  Claim, EvidenceCheck, Evo2ForwardJob, Evo2GenerationResult, Member, Workspace,
  ExperimentComparison, ExperimentManifest, ScientificFramework,
} from './types';

const API_ROOT = import.meta.env.VITE_API_ROOT ?? '';
const BASES = ['A', 'C', 'G', 'T'];
type View = 'experiment' | 'investigate' | 'sandbox' | 'generate' | 'antibody' | 'colony' | 'provenance' | 'frameworks';

const NAV_ITEMS: { id: View; label: string; description: string; icon: typeof Search }[] = [
  { id: 'experiment', label: 'Experiment canvas', description: 'Branch molecular designs', icon: GitBranch },
  { id: 'investigate', label: 'Investigation', description: 'Claims and evidence', icon: Search },
  { id: 'sandbox', label: 'Sequence sandbox', description: 'Replay perturbations', icon: FlaskConical },
  { id: 'generate', label: 'Evo2 generation', description: 'Live hosted NVIDIA call', icon: Wand2 },
  { id: 'antibody', label: 'Antibody complex', description: 'Boltz-2 multi-chain structure', icon: Atom },
  { id: 'colony', label: 'Colony evolution', description: 'Lineage and fitness', icon: GitBranch },
  { id: 'provenance', label: 'Provenance graph', description: 'Trace every artifact', icon: Network },
  { id: 'frameworks', label: 'Scientific stack', description: 'Frameworks and boundaries', icon: Atom },
];

function pathForClaim(workspace: Workspace, claim: Claim): Set<string> {
  const ids = new Set<string>([claim.artifact_digest, claim.verification_digest]);
  const walk = (id: string) => workspace.graph.edges.forEach(edge => {
    if (edge.source === id && !ids.has(edge.target)) { ids.add(edge.target); walk(edge.target); }
  });
  walk(claim.artifact_digest);
  return ids;
}

function shortDigest(value: string | null, size = 10) {
  return value ? `${value.slice(0, size)}…${value.slice(-4)}` : 'not produced';
}

function humanize(value: string) {
  return value.toLowerCase().replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}

function parseFastaOrText(raw: string): string {
  const lines = raw.split(/\r?\n/);
  const sequenceLines: string[] = [];
  let sawHeader = false;
  for (const line of lines) {
    if (line.startsWith('>')) {
      if (sawHeader) break; // stop at the start of a second record: single-sequence inputs only
      sawHeader = true;
      continue;
    }
    sequenceLines.push(line);
  }
  return sequenceLines.join('').replace(/\s/g, '').toUpperCase();
}

function SequenceFileUpload({ onParsed }: { onParsed: (sequence: string) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const handleFile = async (file: File) => {
    setFileError(null);
    if (file.size > 2 * 1024 * 1024) {
      setFileError('File is too large (2MB limit for a single-sequence upload).');
      return;
    }
    const text = await file.text();
    const parsed = parseFastaOrText(text);
    if (!parsed) {
      setFileError('No sequence found in that file.');
      return;
    }
    onParsed(parsed);
  };
  return <span className="file-upload">
    <input
      ref={inputRef}
      type="file"
      accept=".fasta,.fa,.fna,.txt"
      hidden
      onChange={event => { const file = event.target.files?.[0]; if (file) void handleFile(file); event.target.value = ''; }}
    />
    <button type="button" className="secondary-button compact" onClick={() => inputRef.current?.click()}>
      <Upload size={13} /> Upload FASTA
    </button>
    {fileError && <span className="file-upload-error">{fileError}</span>}
  </span>;
}

function statusClass(status: string) {
  if (status === 'SUPPORTED' || status === 'COMPLETED') return 'positive';
  if (status === 'CONTRADICTED' || status === 'FAILED') return 'negative';
  return 'caution';
}

function BoundaryBadge() {
  return <span className="boundary-badge"><ShieldCheck size={14} /> Fixture-safe</span>;
}

function AppLoading({ error }: { error?: string }) {
  return <main className="loading-screen"><div className="loading-mark"><Dna /></div><h1>Concordia Colony</h1><p>{error ?? 'Reconstructing the saved evidence workspace…'}</p></main>;
}

function Sidebar({ view, onView, workspace }: { view: View; onView: (view: View) => void; workspace: Workspace }) {
  return <aside className="sidebar">
    <div className="brand"><span className="brand-mark"><Dna size={20} /></span><span><strong>Concordia</strong><small>Colony</small></span></div>
    <nav aria-label="Scientific workspace"><p className="nav-label">Workspace</p>{NAV_ITEMS.map(item => {
      const Icon = item.icon;
      return <button key={item.id} className={view === item.id ? 'nav-item active' : 'nav-item'} onClick={() => onView(item.id)}><Icon size={18} /><span><strong>{item.label}</strong><small>{item.description}</small></span><ChevronRight size={15} /></button>;
    })}</nav>
    <div className="boundary-card"><div><ShieldCheck size={18} /><strong>Scientific boundary</strong></div><p>Saved audits are fixture-backed. Live model calls and persistent experiments are explicitly labeled and never imply biological validation.</p><span><i /> Provenance before claims</span></div>
    <div className="sidebar-foot"><span>Snapshot</span><code>{shortDigest(workspace.snapshot_digest, 8)}</code></div>
  </aside>;
}

function Topbar({ view, workspace }: { view: View; workspace: Workspace }) {
  const current = NAV_ITEMS.find(item => item.id === view)!;
  return <header className="workspace-topbar"><div><p className="crumb">Workspace <ChevronRight size={13} /> {current.label}</p><h1>{workspace.title}</h1></div><div className="top-actions"><BoundaryBadge /><span className="live-state"><i /> Saved run ready</span></div></header>;
}

function SummaryStrip({ workspace }: { workspace: Workspace }) {
  const members = [workspace.colony.seed_member, ...workspace.colony.members];
  const values = [['Sequence', `${workspace.sequence.sequence.length} bp`, workspace.sequence.assembly], ['Claims', String(workspace.claims.length), 'all require review'], ['Colony', String(members.length), '2 generations'], ['Evidence', String(workspace.graph.nodes.length), 'provenance nodes']];
  return <section className="summary-strip" aria-label="Run summary">{values.map(([label, value, note]) => <div key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>)}<div className="study-state"><span>Real-study gate</span><strong><i /> Awaiting evidence</strong><small>Phase 9 remains closed</small></div></section>;
}

function SequenceRibbon({ workspace, claim, selectedPosition, onPosition }: { workspace: Workspace; claim: Claim; selectedPosition: number; onPosition: (position: number) => void }) {
  const strongest = useMemo(() => {
    const byPosition = new Map<number, number>();
    workspace.effects.forEach(effect => byPosition.set(effect.position, Math.max(byPosition.get(effect.position) ?? 0, Math.abs(effect.delta))));
    return byPosition;
  }, [workspace.effects]);
  const max = Math.max(...strongest.values());
  return <section className="sequence-card card"><div className="card-heading"><div><p className="kicker">Sequence context</p><h2>{workspace.sequence.region}</h2></div><div className="sequence-meta"><span>{workspace.sequence.assembly}</span><span>strand {workspace.sequence.strand}</span><span>zero-based</span></div></div>
    <div className="sequence-ribbon" aria-label="Interactive DNA sequence">{workspace.sequence.sequence.split('').map((base, position) => {
      const inClaim = position >= claim.start && position < claim.end;
      const intensity = (strongest.get(position) ?? 0) / max;
      return <button key={position} aria-label={`Position ${position}, base ${base}`} className={`${inClaim ? 'in-claim' : ''} ${position === selectedPosition ? 'selected' : ''}`} style={{ '--signal-height': `${5 + intensity * 25}px` } as React.CSSProperties} title={`Base ${position}: ${base}; strongest recorded change ${strongest.get(position)?.toFixed(4)}`} onClick={() => onPosition(position)}><span>{base}</span><i /><small>{position % 4 === 0 ? position : ''}</small></button>;
    })}</div><div className="sequence-legend"><span><i className="region-key" /> selected claim region</span><span><i className="signal-key" /> recorded sensitivity</span><span>Click a base to inspect it in the sandbox</span></div>
  </section>;
}

function EvidenceRow({ check }: { check: EvidenceCheck }) {
  return <div className="evidence-row"><span className={check.valid ? 'evidence-icon valid' : 'evidence-icon blocked'}>{check.valid ? <CheckCircle2 size={17} /> : <XCircle size={17} />}</span><div><strong>{humanize(check.family)}</strong><small>{humanize(check.method)}</small></div><span className="evidence-assessment">{check.valid ? humanize(check.assessment) : 'Ineligible fixture'}</span></div>;
}

function Investigation({ workspace, claim, onClaim, selectedPosition, onPosition, onView }: { workspace: Workspace; claim: Claim; onClaim: (id: string) => void; selectedPosition: number; onPosition: (position: number) => void; onView: (view: View) => void }) {
  const highlighted = pathForClaim(workspace, claim);
  return <><div className="view-intro"><div><p className="kicker">Guided investigation</p><h2>Choose a claim, inspect its evidence, then trace the source.</h2></div><button className="secondary-button" onClick={() => onView('provenance')}>Open full graph <ArrowRight size={16} /></button></div><SummaryStrip workspace={workspace} /><SequenceRibbon workspace={workspace} claim={claim} selectedPosition={selectedPosition} onPosition={onPosition} />
    <div className="investigation-grid"><section className="card claim-browser"><div className="card-heading"><div><p className="kicker">1 · Select a claim</p><h2>Questions under audit</h2></div><span className="count-badge">{workspace.claims.length}</span></div><div className="claim-list">{workspace.claims.map((item, index) => <button key={item.id} className={item.id === claim.id ? 'claim-item active' : 'claim-item'} onClick={() => onClaim(item.id)}><span className="claim-number">0{index + 1}</span><span><strong>{item.text}</strong><small>bases {item.start}–{item.end} · {item.sensitivity?.count ?? 0} observations</small></span><ChevronRight size={17} /></button>)}</div></section>
      <section className="card evidence-inspector"><div className="card-heading"><div><p className="kicker">2 · Read the decision</p><h2>Verification result</h2></div><span className={`status-chip ${statusClass(claim.verification.status)}`}>{humanize(claim.verification.status)}</span></div><div className="decision-callout"><CircleHelp size={21} /><div><strong>Why this claim cannot pass</strong><p>{claim.verification.reasons.join(' ')}</p></div></div><div className="evidence-table">{claim.verification.checks.map(check => <EvidenceRow key={check.evidence_id} check={check} />)}</div><div className="scope-line"><span>Model</span><code>{String(claim.scope.model_checkpoint)}</code><span>Target</span><code>{String(claim.scope.scoring_target)}</code></div></section>
      <section className="card trace-preview"><div className="card-heading"><div><p className="kicker">3 · Trace provenance</p><h2>{highlighted.size} connected records</h2></div><button className="icon-button" aria-label="Open provenance graph" onClick={() => onView('provenance')}><Network size={17} /></button></div><div className="trace-flow"><span className="trace-node claim-node">Claim</span><ArrowRight /><span className="trace-node evidence-node">Evidence</span><ArrowRight /><span className="trace-node source-node">Source</span></div><dl className="digest-list"><div><dt>Claim artifact</dt><dd>{shortDigest(claim.artifact_digest)}</dd></div><div><dt>Verification</dt><dd>{shortDigest(claim.verification_digest)}</dd></div></dl><button className="primary-button" onClick={() => onView('provenance')}>Trace this claim <ArrowRight size={16} /></button></section>
    </div></>;
}

function Sandbox({ workspace, position, onPosition }: { workspace: Workspace; position: number; onPosition: (position: number) => void }) {
  const reference = workspace.sequence.sequence[position];
  const [alternate, setAlternate] = useState(BASES.find(base => base !== reference) ?? 'A');
  const [hasRun, setHasRun] = useState(false);
  useEffect(() => { setAlternate(BASES.find(base => base !== reference) ?? 'A'); setHasRun(false); }, [reference, position]);
  const effect = workspace.effects.find(item => item.position === position && item.alternate === alternate);
  const mutated = `${workspace.sequence.sequence.slice(0, position)}${alternate}${workspace.sequence.sequence.slice(position + 1)}`;
  return <><div className="view-intro"><div><p className="kicker">Bounded sequence sandbox</p><h2>Explore a recorded mutation without sending DNA or running a model.</h2></div><BoundaryBadge /></div><div className="sandbox-layout">
    <section className="card sandbox-controls"><div className="card-heading"><div><p className="kicker">Experiment setup</p><h2>Single-base substitution</h2></div><button className="icon-button" aria-label="Reset sandbox" onClick={() => { onPosition(0); setHasRun(false); }}><RotateCcw size={17} /></button></div><label className="control-label" htmlFor="position">Position <strong>{position}</strong></label><input id="position" type="range" min="0" max={workspace.sequence.sequence.length - 1} value={position} onChange={event => { onPosition(Number(event.target.value)); setHasRun(false); }} /><div className="position-scale"><span>0</span><span>{workspace.sequence.sequence.length - 1}</span></div>
      <div className="base-choice"><div><span>Reference</span><strong>{reference}</strong></div><ArrowRight size={20} /><fieldset><legend>Alternate</legend>{BASES.map(base => <button key={base} disabled={base === reference} className={alternate === base ? 'active' : ''} onClick={() => { setAlternate(base); setHasRun(false); }}>{base}</button>)}</fieldset></div><div className="sequence-preview"><span>{workspace.sequence.sequence.slice(Math.max(0, position - 8), position)}</span><strong>{reference}</strong><span>{workspace.sequence.sequence.slice(position + 1, position + 9)}</span><small>reference</small></div><div className="sequence-preview alternate"><span>{mutated.slice(Math.max(0, position - 8), position)}</span><strong>{alternate}</strong><span>{mutated.slice(position + 1, position + 9)}</span><small>alternate</small></div><button className="run-button" disabled={!effect} onClick={() => setHasRun(true)}><Play size={17} /> Replay bounded check</button><p className="control-note"><ShieldCheck size={14} /> Uses one of 144 persisted fixture counterfactuals. No request is sent.</p>
    </section>
    <section className="card sandbox-result"><div className="card-heading"><div><p className="kicker">Execution trace</p><h2>{hasRun ? 'Replay complete' : 'Ready to replay'}</h2></div><span className={`run-indicator ${hasRun ? 'done' : ''}`}><i /> {hasRun ? '4 checks passed' : 'waiting'}</span></div><div className="pipeline">{['Validate DNA alphabet', 'Apply declared substitution', 'Load recorded fixture score', 'Verify artifact identities'].map((step, index) => <div key={step} className={hasRun ? 'complete' : index === 0 ? 'ready' : ''}><span>{hasRun ? <CheckCircle2 size={18} /> : index + 1}</span><strong>{step}</strong><small>{hasRun ? 'complete' : index === 0 ? 'ready' : 'queued'}</small></div>)}</div>
      {hasRun && effect ? <div className="result-panel"><div className="delta-visual"><span>Reference score<strong>{effect.reference_score.toFixed(5)}</strong></span><i /><span>Alternate score<strong>{effect.alternate_score.toFixed(5)}</strong></span></div><div className={`delta-value ${effect.delta < 0 ? 'negative' : 'positive'}`}><span>Recorded change</span><strong>{effect.delta > 0 ? '+' : ''}{effect.delta.toFixed(5)}</strong></div><div className="result-warning"><ShieldCheck size={18} /><p><strong>Software behavior only.</strong> This fixture delta demonstrates the verification workflow; it is not an Evo2 prediction or biological effect.</p></div><dl className="digest-list"><div><dt>Reference artifact</dt><dd>{shortDigest(effect.reference_artifact_hash)}</dd></div><div><dt>Alternate artifact</dt><dd>{shortDigest(effect.alternate_artifact_hash)}</dd></div></dl></div> : <div className="empty-result"><Sparkles size={28} /><strong>Your result will appear here</strong><p>Choose a position and alternate base, then replay the saved check.</p></div>}
    </section></div></>;
}

function LiveCallBadge() {
  return <span className="live-badge"><AlertTriangle size={14} /> Real NVIDIA call</span>;
}

function ExperimentCanvas() {
  const [title, setTitle] = useState('Molecular design study');
  const [sequence, setSequence] = useState('ACGTACGT');
  const [moleculeMode, setMoleculeMode] = useState<'dna' | 'protein'>('dna');
  const [manifest, setManifest] = useState<ExperimentManifest | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [selectedParent, setSelectedParent] = useState<string | null>(null);
  const [position, setPosition] = useState(0);
  const [alternate, setAlternate] = useState('T');
  const [busy, setBusy] = useState(false);
  const [modelBusy, setModelBusy] = useState(false);
  const [canvasError, setCanvasError] = useState<string | null>(null);
  const [structure, setStructure] = useState<{ text: string; format: string } | null>(null);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<ExperimentComparison | null>(null);

  const refresh = async (experimentId: string, accessToken: string) => {
    const response = await fetch(`${API_ROOT}/experiments/${experimentId}`, { headers: { 'X-Concordia-Experiment-Token': accessToken } });
    if (!response.ok) throw new Error('Experiment replay failed');
    setManifest(await response.json() as ExperimentManifest);
  };

  const create = async () => {
    setBusy(true); setCanvasError(null);
    try {
      const experimentResponse = await fetch(`${API_ROOT}/experiments`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
      });
      const created = await experimentResponse.json();
      if (!experimentResponse.ok) throw new Error(created.detail ?? 'Experiment creation failed');
      const experimentId = created.experiment.experiment_id as string;
      const accessToken = created.access_token as string;
      const rootResponse = await fetch(`${API_ROOT}/experiments/${experimentId}/nodes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Concordia-Experiment-Token': accessToken },
        body: JSON.stringify({ kind: `${moleculeMode}_sequence`, operation: 'root', label: `Reference ${moleculeMode.toUpperCase()}`, payload: { payload_type: moleculeMode, sequence } }),
      });
      const root = await rootResponse.json();
      if (!rootResponse.ok) throw new Error(root.detail ?? 'Reference creation failed');
      setToken(accessToken); setSelectedParent(root.node_id);
      await refresh(experimentId, accessToken);
    } catch (reason) {
      setCanvasError(reason instanceof Error ? reason.message : 'Experiment creation failed');
    } finally { setBusy(false); }
  };

  const branch = async () => {
    if (!manifest || !token || !selectedParent) return;
    const parent = manifest.nodes.find(node => node.node_id === selectedParent);
    if (!parent || position >= sequence.length || alternate === sequence[position]) {
      setCanvasError('Choose a valid position and a different alternate base.'); return;
    }
    setBusy(true); setCanvasError(null);
    const mutated = `${sequence.slice(0, position)}${alternate}${sequence.slice(position + 1)}`;
    try {
      const response = await fetch(`${API_ROOT}/experiments/${manifest.experiment.experiment_id}/nodes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Concordia-Experiment-Token': token },
        body: JSON.stringify({ kind: 'dna_sequence', operation: 'mutate', label: `Variant ${manifest.nodes.length}`, branch: `branch-${manifest.nodes.length}`, parent_ids: [selectedParent], payload: { payload_type: 'dna', sequence: mutated }, mutations: [{ position, reference: sequence[position], alternate }] }),
      });
      const node = await response.json();
      if (!response.ok) throw new Error(node.detail ?? 'Branch creation failed');
      setSequence(mutated); setSelectedParent(node.node_id);
      await refresh(manifest.experiment.experiment_id, token);
    } catch (reason) {
      setCanvasError(reason instanceof Error ? reason.message : 'Branch creation failed');
    } finally { setBusy(false); }
  };

  const chooseParent = async (nodeId: string) => {
    if (!manifest || !token) return;
    setCanvasError(null);
    try {
      const response = await fetch(`${API_ROOT}/experiments/${manifest.experiment.experiment_id}/nodes/${nodeId}/payload`, { headers: { 'X-Concordia-Experiment-Token': token } });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? 'Node replay failed');
      if (payload.payload_type === 'dna' || payload.payload_type === 'protein') {
        setMoleculeMode(payload.payload_type); setSelectedParent(nodeId);
        setSequence(payload.sequence as string); setPosition(0); setStructure(null);
      } else if (payload.payload_type === 'structure') {
        setSelectedParent(nodeId);
        setStructure({ text: payload.structure_text as string, format: payload.format as string });
      } else throw new Error('This node has no interactive molecular viewer yet.');
    } catch (reason) { setCanvasError(reason instanceof Error ? reason.message : 'Node replay failed'); }
  };

  const generateBranch = async () => {
    if (!manifest || !token || !selectedParent) return;
    setModelBusy(true); setCanvasError(null);
    try {
      const response = await fetch(`${API_ROOT}/experiments/${manifest.experiment.experiment_id}/operations/evo2/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Concordia-Experiment-Token': token },
        body: JSON.stringify({ parent_node_id: selectedParent, sequence, num_tokens: 8, branch: `evo2-${manifest.nodes.length}` }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? body.message ?? 'Evo2 generation failed');
      setSelectedParent(body.output_node.node_id as string);
      setSequence(body.result.generated_sequence as string);
      await refresh(manifest.experiment.experiment_id, token);
    } catch (reason) {
      setCanvasError(reason instanceof Error ? reason.message : 'Evo2 generation failed');
    } finally { setModelBusy(false); }
  };

  const predictStructure = async () => {
    if (!manifest || !token || !selectedParent || moleculeMode !== 'protein') return;
    setModelBusy(true); setCanvasError(null);
    try {
      const response = await fetch(`${API_ROOT}/experiments/${manifest.experiment.experiment_id}/operations/boltz/predict`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Concordia-Experiment-Token': token },
        body: JSON.stringify({ parent_node_id: selectedParent, sequence, branch: `boltz-${manifest.nodes.length}` }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? body.message ?? 'Boltz prediction failed');
      setSelectedParent(body.output_node.node_id as string);
      setStructure({ text: body.result.structure_text as string, format: body.result.structure_format as string });
      await refresh(manifest.experiment.experiment_id, token);
    } catch (reason) {
      setCanvasError(reason instanceof Error ? reason.message : 'Boltz prediction failed');
    } finally { setModelBusy(false); }
  };

  const saveCandidate = async () => {
    if (!manifest || !token || !selectedParent) return;
    const response = await fetch(`${API_ROOT}/experiments/${manifest.experiment.experiment_id}/candidates/${selectedParent}`, {
      method: 'POST', headers: { 'X-Concordia-Experiment-Token': token },
    });
    if (!response.ok) { setCanvasError('Candidate selection failed'); return; }
    setManifest(await response.json() as ExperimentManifest);
  };

  const toggleCompare = (nodeId: string) => {
    setComparison(null);
    setCompareIds(current => current.includes(nodeId) ? current.filter(id => id !== nodeId) : [...current.slice(-1), nodeId]);
  };

  const compare = async () => {
    if (!manifest || !token || compareIds.length !== 2) return;
    const query = new URLSearchParams({ left: compareIds[0], right: compareIds[1] });
    const response = await fetch(`${API_ROOT}/experiments/${manifest.experiment.experiment_id}/compare?${query}`, { headers: { 'X-Concordia-Experiment-Token': token } });
    if (!response.ok) { setCanvasError('Comparison failed'); return; }
    setComparison(await response.json() as ExperimentComparison);
  };

  return <><div className="view-intro"><div><p className="kicker">Molecular experiment DAG</p><h2>Create, branch, compare, and replay designs without losing lineage.</h2></div><span className="view-stat"><strong>{manifest?.nodes.length ?? 0}</strong> experiment nodes</span></div>
    {!manifest ? <section className="card sandbox-controls"><div className="card-heading"><div><p className="kicker">New experiment</p><h2>Start from DNA or protein</h2></div></div><div className="generation-grid"><button className={moleculeMode === 'dna' ? 'secondary-button active' : 'secondary-button'} onClick={() => { setMoleculeMode('dna'); setSequence('ACGTACGT'); }}>DNA</button><button className={moleculeMode === 'protein' ? 'secondary-button active' : 'secondary-button'} onClick={() => { setMoleculeMode('protein'); setSequence('MKT'); }}>Protein</button></div><label>Experiment title<input value={title} maxLength={200} onChange={event => setTitle(event.target.value)} /></label><label>Reference {moleculeMode.toUpperCase()}<textarea className="generation-textarea" value={sequence} onChange={event => setSequence(event.target.value.toUpperCase())} /></label><button className="run-button" disabled={busy || !title || !sequence || (moleculeMode === 'dna' ? /[^ACGTN]/.test(sequence) : /[^ARNDCQEGHILKMFPSTWYVX]/.test(sequence))} onClick={create}>{busy ? <Loader2 className="spin" size={17} /> : <GitBranch size={17} />} Create experiment</button>{canvasError && <div className="gateway-error"><XCircle size={18} /><p>{canvasError}</p></div>}</section> : <div className="sandbox-layout">
      <section className="card sandbox-controls"><div className="card-heading"><div><p className="kicker">Branch controls</p><h2>{manifest.experiment.title}</h2></div><code>{shortDigest(manifest.manifest_digest)}</code></div><label>Current {moleculeMode.toUpperCase()}<textarea className="generation-textarea" value={sequence} onChange={event => setSequence(event.target.value.toUpperCase())} /></label>{moleculeMode === 'dna' && <><div className="generation-grid"><label>Position<input type="number" min={0} max={Math.max(0, sequence.length - 1)} value={position} onChange={event => setPosition(Number(event.target.value))} /></label><label>Alternate<select value={alternate} onChange={event => setAlternate(event.target.value)}>{BASES.map(base => <option key={base}>{base}</option>)}</select></label></div><button className="run-button" disabled={busy || modelBusy} onClick={branch}>{busy ? <Loader2 className="spin" size={17} /> : <GitBranch size={17} />} Create mutation branch</button><button className="secondary-button" disabled={busy || modelBusy} onClick={generateBranch}>{modelBusy ? <Loader2 className="spin" size={17} /> : <Wand2 size={17} />} Generate branch with Evo2</button></>}{moleculeMode === 'protein' && <button className="run-button" disabled={modelBusy} onClick={predictStructure}>{modelBusy ? <Loader2 className="spin" size={17} /> : <Atom size={17} />} Predict structure with Boltz-2</button>}<button className="secondary-button" disabled={!selectedParent} onClick={saveCandidate}><CheckCircle2 size={17} /> Save selected candidate</button>{structure && <ProteinStructureViewer structureText={structure.text} structureFormat={structure.format} />}{canvasError && <div className="gateway-error"><XCircle size={18} /><p>{canvasError}</p></div>}<p className="control-note"><ShieldCheck size={14} /> The access token stays in this page state. Model actions make real rate-limited NVIDIA calls and remain non-validated computational outputs.</p></section>
      <section className="card sandbox-result"><div className="card-heading"><div><p className="kicker">Lineage</p><h2>Immutable experiment nodes</h2></div><span className="count-badge">{manifest.edges.length} edges</span></div><div className="claim-list">{manifest.nodes.map(node => <div key={node.node_id} className={selectedParent === node.node_id ? 'claim-item active' : 'claim-item'}><button onClick={() => void chooseParent(node.node_id)}><span className="claim-number">{node.kind === 'dna_sequence' ? 'DNA' : node.kind === 'protein_sequence' ? 'PRO' : node.kind === 'structure' ? '3D' : 'RUN'}</span><span><strong>{node.label}{manifest.selected_candidate_ids.includes(node.node_id) ? ' ★' : ''}</strong><small>{humanize(node.operation)} · {node.branch} · {shortDigest(node.artifact_digest)}</small></span><ChevronRight size={17} /></button><input aria-label={`Compare ${node.label}`} type="checkbox" checked={compareIds.includes(node.node_id)} onChange={() => toggleCompare(node.node_id)} /></div>)}</div><button className="secondary-button" disabled={compareIds.length !== 2} onClick={compare}>Compare selected nodes</button>{comparison && <div className="result-panel"><strong>{comparison.comparable ? 'Comparable' : 'Not comparable'}</strong>{comparison.comparable ? <p>{comparison.differing_positions.length} differing positions · length delta {comparison.length_delta ?? '—'}{comparison.value_delta !== null ? ` · value delta ${comparison.value_delta}` : ''}</p> : <p>{comparison.reasons.join(' ')}</p>}</div>}</section>
    </div>}</>;
}

function GenerationPlayground() {
  const [sequence, setSequence] = useState('ACGTACGT');
  const [numTokens, setNumTokens] = useState(8);
  const [temperature, setTemperature] = useState(0.7);
  const [topK, setTopK] = useState(3);
  const [status, setStatus] = useState<'idle' | 'loading' | 'error' | 'done'>('idle');
  const [result, setResult] = useState<Evo2GenerationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const invalidSequence = sequence.length === 0 || /[^ACGTacgt]/.test(sequence);

  const run = async () => {
    setStatus('loading'); setError(null);
    try {
      const response = await fetch(`${API_ROOT}/nvidia/evo2/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sequence: sequence.toUpperCase(), num_tokens: numTokens, temperature, top_k: topK }),
      });
      const body = await response.json();
      if (!response.ok) {
        const retryAfter = response.headers.get('Retry-After');
        const suffix = response.status === 429 && retryAfter ? ` Retry in ${retryAfter}s.` : '';
        throw new Error(`${body.detail ?? body.message ?? 'Generation request failed'}${suffix}`);
      }
      setResult(body as Evo2GenerationResult);
      setStatus('done');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Generation request failed');
      setStatus('error');
    }
  };

  return <><div className="view-intro"><div><p className="kicker">Interactive Evo2 generation</p><h2>Send a seed sequence to NVIDIA's hosted Evo2 and watch the real response.</h2></div><LiveCallBadge /></div><div className="sandbox-layout">
    <section className="card sandbox-controls"><div className="card-heading"><div><p className="kicker">Request</p><h2>Hosted <code>arc/evo2-40b</code> generation</h2></div></div>
      <div className="control-label"><label htmlFor="gen-sequence">Seed sequence</label><SequenceFileUpload onParsed={setSequence} /></div>
      <textarea id="gen-sequence" className="generation-textarea" value={sequence} maxLength={8192} spellCheck={false} onChange={event => setSequence(event.target.value.toUpperCase())} />
      {invalidSequence && <p className="field-error">Only A, C, G, T bases are accepted.</p>}
      <div className="generation-grid">
        <label>Tokens<input type="number" min={1} max={1200} value={numTokens} onChange={event => setNumTokens(Number(event.target.value))} /></label>
        <label>Temperature<input type="number" min={0} max={1.3} step={0.1} value={temperature} onChange={event => setTemperature(Number(event.target.value))} /></label>
        <label>Top K<input type="number" min={0} max={6} value={topK} onChange={event => setTopK(Number(event.target.value))} /></label>
      </div>
      <button className="run-button" disabled={invalidSequence || status === 'loading'} onClick={run}>{status === 'loading' ? <Loader2 size={17} className="spin" /> : <Play size={17} />} {status === 'loading' ? 'Calling NVIDIA…' : 'Generate'}</button>
      <p className="control-note"><AlertTriangle size={14} /> This spends your deployment's rate-limited NVIDIA quota. Generation is not an Evo2 forward score.</p>
    </section>
    <section className="card sandbox-result"><div className="card-heading"><div><p className="kicker">Response</p><h2>{status === 'done' ? 'Generation complete' : status === 'loading' ? 'Awaiting NVIDIA' : status === 'error' ? 'Request failed' : 'Ready to generate'}</h2></div><span className={`run-indicator ${status === 'done' ? 'done' : ''}`}><i /> {status === 'done' ? 'real response' : status === 'loading' ? 'in flight' : 'idle'}</span></div>
      {status === 'error' && error && <div className="gateway-error"><XCircle size={18} /><p>{error}</p></div>}
      {status === 'done' && result ? <div className="result-panel">
        <div className="sequence-preview alternate"><span /><strong>{result.generated_sequence}</strong><span /><small>generated</small></div>
        <div className="probability-bars">{result.sampled_probabilities.map((value, index) => <div key={index}><span>{result.generated_sequence[index] ?? '·'}</span><div><i style={{ width: `${value * 100}%` }} /></div><strong>{value.toFixed(2)}</strong></div>)}</div>
        <div className="result-warning"><ShieldCheck size={18} /><p><strong>Not scientific evidence.</strong> {result.limitations.join(' ')}</p></div>
        <dl className="digest-list"><div><dt>Request artifact</dt><dd>{shortDigest(result.request_artifact_digest)}</dd></div><div><dt>Response artifact</dt><dd>{shortDigest(result.response_artifact_digest)}</dd></div><div><dt>Elapsed</dt><dd>{result.elapsed_seconds.toFixed(2)}s</dd></div></dl>
      </div> : status !== 'error' && <div className="empty-result"><Sparkles size={28} /><strong>Your generated sequence will appear here</strong><p>Edit the seed sequence and press Generate to call the hosted NVIDIA endpoint.</p></div>}
    </section></div></>;
}

const FORWARD_WINDOW_LENGTH = 8192;
const TERMINAL_JOB_STATUSES = new Set(['COMPLETED', 'FAILED', 'REJECTED_BUSY']);

function LikelihoodTrack({ values, sequence }: { values: number[]; sequence: string }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const width = 1000;
  const height = 160;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1e-9);
  const mean = values.reduce((total, value) => total + value, 0) / values.length;
  const yFor = (value: number) => height - ((value - min) / span) * (height - 10) - 5;
  const path = useMemo(
    () => values.map((value, index) => `${index === 0 ? 'M' : 'L'}${(index / (values.length - 1)) * width},${yFor(value)}`).join(' '),
    [values],
  );
  const worstIndex = values.indexOf(min);
  const bestIndex = values.indexOf(max);
  const onMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    setHoverIndex(Math.round(ratio * (values.length - 1)));
  };
  const describedIndex = hoverIndex ?? worstIndex;
  const describedBase = sequence[describedIndex + 1] ?? '—';
  return <div className="likelihood-track">
    <div className="likelihood-track-header">
      <span>Per-position next-base log-likelihood <small>({values.length.toLocaleString()} scored positions)</small></span>
      <span className="likelihood-legend"><i className="worst-key" /> lowest confidence<i className="best-key" /> highest confidence</span>
    </div>
    <svg
      ref={svgRef}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="likelihood-svg"
      onMouseMove={onMove}
      onMouseLeave={() => setHoverIndex(null)}
    >
      <line x1={0} x2={width} y1={yFor(mean)} y2={yFor(mean)} className="likelihood-mean-line" />
      <path d={path} className="likelihood-path" />
      <circle cx={(worstIndex / (values.length - 1)) * width} cy={yFor(min)} r={4} className="likelihood-marker worst" />
      <circle cx={(bestIndex / (values.length - 1)) * width} cy={yFor(max)} r={4} className="likelihood-marker best" />
      {hoverIndex !== null && <line x1={(hoverIndex / (values.length - 1)) * width} x2={(hoverIndex / (values.length - 1)) * width} y1={0} y2={height} className="likelihood-hover-line" />}
    </svg>
    <div className="likelihood-readout">
      <span>{hoverIndex !== null ? `Position ${describedIndex + 1}` : `Lowest confidence — position ${describedIndex + 1}`}</span>
      <code>base {describedBase}</code>
      <strong>{values[describedIndex].toFixed(4)}</strong>
    </div>
    <p className="field-hint">Hover the curve to inspect any position. Base {describedIndex + 1} is predicted from bases 1–{describedIndex + 1} of your input under the frozen causal scoring contract — this shows where the model's next-base confidence rises and falls across the sequence, not a biological signal.</p>
  </div>;
}

const CODON_TABLE: Record<string, string> = {
  TTT: 'F', TTC: 'F', TTA: 'L', TTG: 'L', CTT: 'L', CTC: 'L', CTA: 'L', CTG: 'L',
  ATT: 'I', ATC: 'I', ATA: 'I', ATG: 'M', GTT: 'V', GTC: 'V', GTA: 'V', GTG: 'V',
  TCT: 'S', TCC: 'S', TCA: 'S', TCG: 'S', CCT: 'P', CCC: 'P', CCA: 'P', CCG: 'P',
  ACT: 'T', ACC: 'T', ACA: 'T', ACG: 'T', GCT: 'A', GCC: 'A', GCA: 'A', GCG: 'A',
  TAT: 'Y', TAC: 'Y', TAA: '*', TAG: '*', CAT: 'H', CAC: 'H', CAA: 'Q', CAG: 'Q',
  AAT: 'N', AAC: 'N', AAA: 'K', AAG: 'K', GAT: 'D', GAC: 'D', GAA: 'E', GAG: 'E',
  TGT: 'C', TGC: 'C', TGA: '*', TGG: 'W', CGT: 'R', CGC: 'R', CGA: 'R', CGG: 'R',
  AGT: 'S', AGC: 'S', AGA: 'R', AGG: 'R', GGT: 'G', GGC: 'G', GGA: 'G', GGG: 'G',
};

function translateDna(dna: string, frame: 1 | 2 | 3): { protein: string; stopCodonHit: boolean } {
  let protein = '';
  let stopCodonHit = false;
  for (let index = frame - 1; index + 3 <= dna.length; index += 3) {
    const codon = dna.slice(index, index + 3);
    const aminoAcid = CODON_TABLE[codon];
    if (!aminoAcid || aminoAcid === '*') { stopCodonHit = Boolean(aminoAcid); break; }
    protein += aminoAcid;
  }
  return { protein, stopCodonHit };
}

function ProteinStructureViewer({ structureText, structureFormat }: { structureText: string; structureFormat: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loadingViewer, setLoadingViewer] = useState(true);
  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;
    let cleanupViewer: (() => void) | null = null;
    setLoadingViewer(true);
    const modelFormat = structureFormat.toLowerCase().includes('cif') ? 'cif' : 'pdb';
    import('3dmol').then(({ createViewer }) => {
      if (cancelled || !containerRef.current) return;
      const viewer = createViewer(containerRef.current, { backgroundColor: '#07110f' });
      viewer.addModel(structureText, modelFormat);
      viewer.setStyle({}, { cartoon: { color: 'spectrum' } });
      viewer.zoomTo();
      viewer.render();
      setLoadingViewer(false);
      const handleResize = () => viewer.resize();
      window.addEventListener('resize', handleResize);
      cleanupViewer = () => { window.removeEventListener('resize', handleResize); viewer.clear(); };
    });
    return () => { cancelled = true; cleanupViewer?.(); };
  }, [structureText, structureFormat]);
  return <div ref={containerRef} className="protein-viewer">{loadingViewer && <div className="protein-viewer-loading"><Loader2 size={22} className="spin" /> Loading 3D viewer…</div>}</div>;
}

interface BoltzPredictionResult {
  structure_text: string; structure_format: string; confidence_scores: number[];
  limitations: string[]; elapsed_seconds: number;
}

function ProteinStructurePanel() {
  const [mode, setMode] = useState<'dna' | 'protein'>('dna');
  const [input, setInput] = useState('');
  const [frame, setFrame] = useState<1 | 2 | 3>(1);
  const [status, setStatus] = useState<'idle' | 'loading' | 'error' | 'done'>('idle');
  const [result, setResult] = useState<BoltzPredictionResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const translation = useMemo(
    () => mode === 'dna' ? translateDna(input.toUpperCase().replace(/[^ACGT]/g, ''), frame) : { protein: input.toUpperCase().replace(/[^ARNDCQEGHILKMFPSTWYV]/g, ''), stopCodonHit: false },
    [mode, input, frame],
  );
  const protein = translation.protein;
  const invalid = protein.length === 0 || protein.length > 2000;

  const predict = async () => {
    setStatus('loading'); setError(null);
    try {
      const response = await fetch(`${API_ROOT}/nvidia/boltz/predict`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sequence: protein }),
      });
      const body = await response.json();
      if (!response.ok) {
        const retryAfter = response.headers.get('Retry-After');
        const suffix = response.status === 429 && retryAfter ? ` Retry in ${retryAfter}s.` : '';
        throw new Error(`${body.detail ?? body.message ?? 'Structure prediction failed'}${suffix}`);
      }
      setResult(body);
      setStatus('done');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Structure prediction failed');
      setStatus('error');
    }
  };

  return <section className="card protein-panel"><div className="card-heading"><div><p className="kicker">Protein structure (NVIDIA Boltz-2)</p><h2>Translate DNA and fold the resulting protein</h2></div><LiveCallBadge /></div>
    <p className="forward-warning"><AlertTriangle size={14} /> ESMFold was NVIDIA's original NIM here but is confirmed retired (404 for any account); this panel now calls Boltz-2 instead, confirmed live. Prediction can take up to a few minutes — NVIDIA may queue the job. The alignment sent is a single self-referenced sequence, not a real MSA, which reduces accuracy.</p>
    <div className="mode-toggle"><button type="button" className={mode === 'dna' ? 'active' : ''} onClick={() => setMode('dna')}>From DNA</button><button type="button" className={mode === 'protein' ? 'active' : ''} onClick={() => setMode('protein')}>Protein sequence</button></div>
    <div className="protein-layout">
      <div>
        <div className="control-label"><label htmlFor="protein-input">{mode === 'dna' ? 'DNA sequence' : 'Amino acid sequence'}</label><SequenceFileUpload onParsed={setInput} /></div>
        <textarea id="protein-input" className="generation-textarea" value={input} spellCheck={false} onChange={event => setInput(event.target.value)} placeholder={mode === 'dna' ? 'Paste or upload a DNA sequence…' : 'Paste or upload a protein sequence…'} />
        {mode === 'dna' && <div className="generation-grid"><label>Reading frame<select value={frame} onChange={event => setFrame(Number(event.target.value) as 1 | 2 | 3)}><option value={1}>1</option><option value={2}>2</option><option value={3}>3</option></select></label></div>}
        <div className="translation-preview"><span>{mode === 'dna' ? 'Translated protein' : 'Protein'} ({protein.length} aa{translation.stopCodonHit ? ', stopped at a stop codon' : ''})</span><code>{protein || '—'}</code></div>
        <button className="run-button" disabled={invalid || status === 'loading'} onClick={predict}>{status === 'loading' ? <Loader2 size={17} className="spin" /> : <Atom size={17} />} {status === 'loading' ? 'Calling NVIDIA (may take a minute)…' : 'Predict 3D structure'}</button>
        {protein.length > 4096 && <p className="field-error">Boltz-2 accepts at most 4,096 amino acids.</p>}
        {status === 'error' && error && <div className="gateway-error"><XCircle size={18} /><p>{error}</p></div>}
      </div>
      <div className="protein-result">
        {status === 'done' && result ? <>
          <ProteinStructureViewer structureText={result.structure_text} structureFormat={result.structure_format} />
          {result.confidence_scores?.length > 0 && <div className="translation-preview"><span>Confidence scores (raw, uninterpreted)</span><code>{result.confidence_scores.map(v => v.toFixed(3)).join(', ')}</code></div>}
          <div className="result-warning"><ShieldCheck size={18} /><p><strong>Not scientific evidence.</strong> {result.limitations.join(' ')}</p></div>
        </> : <div className="empty-result"><Atom size={28} /><strong>Structure will render here</strong><p>Enter a sequence and predict to call the hosted Boltz-2 NIM.</p></div>}
      </div>
    </div>
  </section>;
}

interface BoltzComplexPredictionResult {
  structure_text: string; structure_format: string; confidence_scores: number[];
  limitations: string[]; elapsed_seconds: number; input_payload_hash: string;
  request_artifact_digest: string; response_artifact_digest: string;
}

function AntibodyComplexPanel() {
  const [heavy, setHeavy] = useState('EVQLVESGGGLVQPGGSLRLSCAAS');
  const [light, setLight] = useState('DIQMTQSPSSLSASVGDRVTITC');
  const [antigen, setAntigen] = useState('MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ');
  const [status, setStatus] = useState<'idle' | 'loading' | 'error' | 'done'>('idle');
  const [result, setResult] = useState<BoltzComplexPredictionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const invalid = [heavy, light, antigen].some(sequence => !/^[ARNDCQEGHILKMFPSTWYV]+$/i.test(sequence) || sequence.length === 0);

  const predict = async () => {
    setStatus('loading'); setError(null);
    try {
      const response = await fetch(`${API_ROOT}/nvidia/boltz/complex`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ polymers: [
          { id: 'H', molecule_type: 'protein', sequence: heavy },
          { id: 'L', molecule_type: 'protein', sequence: light },
          { id: 'A', molecule_type: 'protein', sequence: antigen },
        ] }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? body.message ?? 'Complex prediction failed');
      setResult(body as BoltzComplexPredictionResult); setStatus('done');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Complex prediction failed'); setStatus('error');
    }
  };

  return <><div className="view-intro"><div><p className="kicker">Antibody design foundation</p><h2>Validate a multi-chain antibody–antigen input and inspect a Boltz-2 complex hypothesis.</h2></div><LiveCallBadge /></div>
    <section className="card protein-panel"><div className="card-heading"><div><p className="kicker">NVIDIA Boltz-2 complex</p><h2>Heavy chain, light chain, and antigen</h2></div><span className="live-badge"><AlertTriangle size={14} /> Rate-limited live call</span></div>
      <p className="forward-warning"><AlertTriangle size={14} /> This panel performs structure prediction only. RFantibody/RFdiffusion generation, ProteinMPNN sequence design, antibody numbering, and interface scoring are separate future workflow steps.</p>
      <div className="generation-grid antibody-fields">
        <label>Heavy chain<textarea className="generation-textarea" value={heavy} onChange={event => setHeavy(event.target.value.toUpperCase())} /></label>
        <label>Light chain<textarea className="generation-textarea" value={light} onChange={event => setLight(event.target.value.toUpperCase())} /></label>
        <label>Antigen<textarea className="generation-textarea" value={antigen} onChange={event => setAntigen(event.target.value.toUpperCase())} /></label>
      </div>
      {invalid && <p className="field-error">Use only the 20 standard amino-acid letters in all three chains.</p>}
      <button className="run-button" disabled={invalid || status === 'loading'} onClick={predict}>{status === 'loading' ? <Loader2 size={17} className="spin" /> : <Atom size={17} />} {status === 'loading' ? 'Calling NVIDIA (may take a minute)…' : 'Predict antibody complex'}</button>
      {status === 'error' && error && <div className="gateway-error"><XCircle size={18} /><p>{error}</p></div>}
      {status === 'done' && result ? <div className="protein-result antibody-result"><ProteinStructureViewer structureText={result.structure_text} structureFormat={result.structure_format} /><div className="result-warning"><ShieldCheck size={18} /><p><strong>Not scientific evidence.</strong> {result.limitations.join(' ')}</p></div><dl className="digest-list"><div><dt>Input payload</dt><dd>{shortDigest(result.input_payload_hash)}</dd></div><div><dt>Request artifact</dt><dd>{shortDigest(result.request_artifact_digest)}</dd></div><div><dt>Response artifact</dt><dd>{shortDigest(result.response_artifact_digest)}</dd></div><div><dt>Elapsed</dt><dd>{result.elapsed_seconds.toFixed(2)}s</dd></div></dl></div> : status !== 'error' && <div className="empty-result"><Atom size={28} /><strong>Complex structure will render here</strong><p>Submit the three chains to call the hosted Boltz-2 NIM.</p></div>}
    </section></>;
}

function ForwardScoringPanel() {
  const [sequence, setSequence] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [job, setJob] = useState<Evo2ForwardJob | null>(null);
  const [submittedSequence, setSubmittedSequence] = useState('');
  const lengthError = sequence.length > 0 && sequence.length !== FORWARD_WINDOW_LENGTH;
  const baseError = /[^ACGTacgt]/.test(sequence);

  useEffect(() => {
    if (!job || TERMINAL_JOB_STATUSES.has(job.status)) return;
    const timer = setInterval(() => {
      fetch(`${API_ROOT}/nvidia/evo2/forward/${job.job_id}`)
        .then(response => response.json())
        .then((next: Evo2ForwardJob) => setJob(next))
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(timer);
  }, [job]);

  const submit = async () => {
    setSubmitting(true); setSubmitError(null); setJob(null);
    const requestSequence = sequence.toUpperCase();
    setSubmittedSequence(requestSequence);
    try {
      const response = await fetch(`${API_ROOT}/nvidia/evo2/forward`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sequence: requestSequence }),
      });
      const body = await response.json();
      if (!response.ok) {
        const retryAfter = response.headers.get('Retry-After');
        const suffix = response.status === 429 && retryAfter ? ` Retry in ${retryAfter}s.` : '';
        throw new Error(`${body.detail ?? body.message ?? 'Forward scoring request failed'}${suffix}`);
      }
      setJob({ job_id: body.job_id, status: body.status, submitted_at: Date.now() / 1000, completed_at: null, result: null, error: null });
    } catch (reason) {
      setSubmitError(reason instanceof Error ? reason.message : 'Forward scoring request failed');
    } finally {
      setSubmitting(false);
    }
  };

  const disabled = submitting || sequence.length !== FORWARD_WINDOW_LENGTH || baseError || (!!job && !TERMINAL_JOB_STATUSES.has(job.status));
  const fillTestSequence = () => {
    const bases = 'ACGT';
    let generated = '';
    for (let index = 0; index < FORWARD_WINDOW_LENGTH; index += 1) {
      generated += bases[Math.floor(Math.random() * 4)];
    }
    setSequence(generated);
    setJob(null); setSubmitError(null);
  };

  return <section className="card forward-panel"><div className="card-heading"><div><p className="kicker">Real forward scoring</p><h2>One Evo2 7B forward pass on ZeroGPU</h2></div><LiveCallBadge /></div>
    <p className="forward-warning"><AlertTriangle size={14} /> Unverified: this worker has never completed a successful run. Early attempts may fail or time out. At most one job runs at a time for all visitors.</p>
    <div className="control-label"><label htmlFor="forward-sequence">Exact {FORWARD_WINDOW_LENGTH.toLocaleString()}-base sequence <strong>{sequence.length.toLocaleString()} / {FORWARD_WINDOW_LENGTH.toLocaleString()}</strong></label><span className="control-label-actions"><SequenceFileUpload onParsed={value => { setSequence(value); setJob(null); setSubmitError(null); }} /><button type="button" className="secondary-button compact" onClick={fillTestSequence}><RotateCcw size={13} /> Fill random test sequence</button></span></div>
    <p className="field-hint">The frozen HBB window itself is only pinned by SHA-256 in this repository, not stored as raw text — paste your own exact {FORWARD_WINDOW_LENGTH.toLocaleString()}-base sequence, or use the random filler to exercise the pipeline with a synthetic, non-biological test input.</p>
    <textarea id="forward-sequence" className="generation-textarea" value={sequence} maxLength={FORWARD_WINDOW_LENGTH} spellCheck={false} onChange={event => setSequence(event.target.value.toUpperCase())} />
    {lengthError && <p className="field-error">Sequence must be exactly {FORWARD_WINDOW_LENGTH.toLocaleString()} bases.</p>}
    {baseError && <p className="field-error">Only A, C, G, T bases are accepted.</p>}
    <button className="run-button" disabled={disabled} onClick={submit}>{submitting || (job && !TERMINAL_JOB_STATUSES.has(job.status)) ? <Loader2 size={17} className="spin" /> : <Play size={17} />} {job && !TERMINAL_JOB_STATUSES.has(job.status) ? 'Running on ZeroGPU…' : 'Submit forward pass'}</button>
    {submitError && <div className="gateway-error"><XCircle size={18} /><p>{submitError}</p></div>}
    {job && <div className="forward-job-status"><span className={`status-chip ${job.status === 'COMPLETED' ? 'positive' : job.status === 'FAILED' || job.status === 'REJECTED_BUSY' ? 'negative' : 'caution'}`}>{humanize(job.status)}</span><code>{job.job_id.slice(0, 12)}</code></div>}
    {job?.status === 'FAILED' && job.error && <div className="gateway-error"><XCircle size={18} /><p>{job.error}</p></div>}
    {job?.status === 'REJECTED_BUSY' && <div className="gateway-error"><XCircle size={18} /><p>Another visitor's job was already running. Try again shortly.</p></div>}
    {job?.status === 'COMPLETED' && job.result && <div className="result-panel">
      <div className="delta-value positive"><span>Mean log-likelihood</span><strong>{job.result.score.toFixed(5)}</strong></div>
      {job.result.runtime_metadata.target_token_log_probabilities && job.result.runtime_metadata.target_token_log_probabilities.length > 1 &&
        <LikelihoodTrack values={job.result.runtime_metadata.target_token_log_probabilities} sequence={submittedSequence} />}
      <div className="result-warning"><ShieldCheck size={18} /><p><strong>{job.result.scientific_use_allowed ? 'In scope, but still a single real run.' : 'Not scientific evidence.'}</strong> {job.result.scientific_use_allowed ? 'This execution matched the frozen scoring protocol exactly.' : 'This execution did not match the frozen scoring protocol scope.'}</p></div>
      <dl className="digest-list"><div><dt>Execution mode</dt><dd>{job.result.execution_mode}</dd></div><div><dt>Scored tokens</dt><dd>{job.result.runtime_metadata.scored_token_count ?? '—'}</dd></div><div><dt>Output artifact</dt><dd>{shortDigest(job.result.output_artifact_digest ?? '')}</dd></div></dl>
    </div>}
  </section>;
}

function FitnessBars({ member }: { member: Member }) {
  if (!member.fitness) return <div className="empty-inline">The seed has no fitness measurement.</div>;
  const entries = Object.entries(member.fitness.vector).filter(([, value]) => typeof value === 'number').slice(0, 9);
  return <div className="fitness-bars">{entries.map(([label, value]) => { const normalized = label.includes('runtime') || label.includes('usage') ? Math.min(1, value / 200) : Math.min(1, Math.max(0, value)); return <div key={label}><span>{humanize(label)}</span><div><i style={{ width: `${normalized * 100}%` }} /></div><strong>{value.toFixed(value < 10 ? 3 : 0)}</strong></div>; })}</div>;
}

function Frameworks({ frameworks }: { frameworks: ScientificFramework[] }) {
  return <><div className="view-intro"><div><p className="kicker">Scientific stack</p><h2>Frameworks are shown with their execution role and evidence boundary.</h2></div><span className="view-stat"><strong>{frameworks.length}</strong> registered integrations</span></div>
    <div className="framework-grid">{frameworks.map(framework => <article className="card framework-card" key={framework.id}>
      <div className="card-heading"><div><p className="kicker">{humanize(framework.category)}</p><h2>{framework.name}</h2></div><span className={`status-chip ${framework.status === 'integrated' ? 'positive' : framework.status === 'boundary' ? 'caution' : 'negative'}`}>{humanize(framework.status)}</span></div>
      <p className="framework-role">{framework.role}</p><dl className="digest-list"><div><dt>Integration</dt><dd>{framework.integration}</dd></div><div><dt>Execution</dt><dd><code>{framework.execution_mode}</code></dd></div></dl>
      <div className="framework-boundary"><ShieldCheck size={16} /><p>{framework.scientific_boundary}</p></div><a className="secondary-button" href={framework.official_url} target="_blank" rel="noreferrer">Official documentation <ArrowRight size={14} /></a>
    </article>)}</div></>;
}

function Colony({ workspace }: { workspace: Workspace }) {
  const [liveColony, setLiveColony] = useState<Workspace['colony'] | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [params, setParams] = useState({ population_size: 3, generations: 2, survivor_count: 1 });
  const colonyData = liveColony ?? workspace.colony;
  const members = [colonyData.seed_member, ...colonyData.members];
  const maxGeneration = Math.max(...members.map(member => member.generation));
  const [generation, setGeneration] = useState(maxGeneration);
  const visible = members.filter(member => member.generation <= generation);
  const [selectedId, setSelectedId] = useState(visible.at(-1)?.member_id ?? members[0].member_id);
  const selected = members.find(member => member.member_id === selectedId) ?? members[0];
  const fallbackId = visible.at(-1)?.member_id ?? members[0].member_id;
  useEffect(() => {
    if (selected.generation > generation) setSelectedId(fallbackId);
  }, [fallbackId, generation, selected.generation]);
  useEffect(() => {
    setGeneration(Math.max(...members.map(member => member.generation)));
    setSelectedId(members[0].member_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [colonyData]);
  const survivors = new Set(colonyData.selections.flatMap(selection => selection.survivor_ids));

  const runLive = async () => {
    setRunning(true); setRunError(null);
    try {
      const response = await fetch(`${API_ROOT}/colony/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
      const body = await response.json();
      if (!response.ok) {
        const retryAfter = response.headers.get('Retry-After');
        const suffix = response.status === 429 && retryAfter ? ` Retry in ${retryAfter}s.` : '';
        throw new Error(`${body.detail ?? body.message ?? 'Colony run failed'}${suffix}`);
      }
      setLiveColony(body.colony);
    } catch (reason) {
      setRunError(reason instanceof Error ? reason.message : 'Colony run failed');
    } finally {
      setRunning(false);
    }
  };
  return <><div className="view-intro"><div><p className="kicker">Evolution audit</p><h2>Scrub through generations and inspect why workflows survived.</h2></div><span className="view-stat"><strong>{members.length}</strong> total members</span></div>
    <section className="card live-colony-control"><div className="card-heading"><div><p className="kicker">Run it yourself</p><h2>Execute a fresh colony simulation now</h2></div>{liveColony ? <span className="live-badge"><AlertTriangle size={14} /> Live run</span> : <BoundaryBadge />}</div>
      <p className="field-hint">Real scheduling code runs end to end on this request — new genome, real mutations, real deterministic fitness, real survivor selection. No LLM or GPU; the task itself is a frozen software fixture, so results stay non-scientific.</p>
      <div className="generation-grid">
        <label>Population<input type="number" min={1} max={6} value={params.population_size} onChange={event => setParams(p => ({ ...p, population_size: Number(event.target.value) }))} /></label>
        <label>Generations<input type="number" min={1} max={3} value={params.generations} onChange={event => setParams(p => ({ ...p, generations: Number(event.target.value) }))} /></label>
        <label>Survivors<input type="number" min={1} max={params.population_size} value={params.survivor_count} onChange={event => setParams(p => ({ ...p, survivor_count: Number(event.target.value) }))} /></label>
      </div>
      <div className="live-colony-actions">
        <button className="run-button live-colony-run" disabled={running} onClick={runLive}>{running ? <Loader2 size={17} className="spin" /> : <Play size={17} />} {running ? 'Running…' : 'Run live simulation'}</button>
        {liveColony && <button className="secondary-button compact" onClick={() => setLiveColony(null)}><RotateCcw size={13} /> Reset to saved fixture</button>}
      </div>
      {runError && <div className="gateway-error"><XCircle size={18} /><p>{runError}</p></div>}
    </section>
    <section className="card generation-control"><div><span>Seed</span><strong>Generation {generation}</strong><span>Generation {maxGeneration}</span></div><input aria-label="Generation" type="range" min="0" max={maxGeneration} value={generation} onChange={event => setGeneration(Number(event.target.value))} /><div className="generation-dots">{Array.from({ length: maxGeneration + 1 }, (_, index) => <button aria-label={`Show generation ${index}`} key={index} className={index <= generation ? 'active' : ''} onClick={() => setGeneration(index)} />)}</div></section>
    <div className="colony-layout"><section className="card lineage-board"><div className="card-heading"><div><p className="kicker">Lineage</p><h2>Isolated workflow descendants</h2></div><span className="count-badge">through G{generation}</span></div><div className="generation-columns">{Array.from({ length: generation + 1 }, (_, value) => <div key={value} className="generation-column"><p>Generation {value}</p>{visible.filter(member => member.generation === value).map(member => <button key={member.member_id} className={selected.member_id === member.member_id ? 'member-card active' : 'member-card'} onClick={() => setSelectedId(member.member_id)}><span className={`member-orb ${member.status.toLowerCase()}`}><Dna size={16} /></span><span><strong>{member.member_id.slice(0, 12)}</strong><small>{humanize(member.status)}{survivors.has(member.member_id) ? ' · survivor' : ''}</small></span>{member.fitness && <b>{member.fitness.weighted_score.toFixed(3)}</b>}</button>)}</div>)}</div></section>
      <section className="card member-inspector"><div className="card-heading"><div><p className="kicker">Selected member</p><h2>{selected.member_id.slice(0, 16)}</h2></div><span className={`status-chip ${selected.status === 'EXTINCT' ? 'negative' : 'positive'}`}>{humanize(selected.status)}</span></div><div className="member-facts"><div><span>Generation</span><strong>{selected.generation}</strong></div><div><span>Weighted fitness</span><strong>{selected.fitness?.weighted_score.toFixed(3) ?? '—'}</strong></div><div><span>Isolation</span><strong>{selected.isolation_id.split('-').at(-1)}</strong></div></div><FitnessBars member={selected} /><dl className="digest-list"><div><dt>Genome</dt><dd>{shortDigest(selected.genome_digest)}</dd></div><div><dt>Mutation</dt><dd>{shortDigest(selected.mutation_digest)}</dd></div><div><dt>Output</dt><dd>{shortDigest(selected.output_digest)}</dd></div></dl>{selected.terminal_reason && <div className="terminal-reason"><XCircle size={16} /><span><strong>Extinction reason</strong>{humanize(selected.terminal_reason)}</span></div>}</section>
    </div></>;
}

function Provenance({ workspace, claim, selectedNode, onNode }: { workspace: Workspace; claim: Claim; selectedNode: Set<string>; onNode: (id: string) => void }) {
  const effective = selectedNode.size ? selectedNode : pathForClaim(workspace, claim);
  const focusedId = selectedNode.values().next().value as string | undefined;
  const focused = workspace.graph.nodes.find(node => node.id === focusedId);
  const connections = focusedId ? workspace.graph.edges.filter(edge => edge.source === focusedId || edge.target === focusedId) : [];
  return <><div className="view-intro"><div><p className="kicker">Evidence provenance</p><h2>Follow claims back to immutable sources and activities.</h2></div><span className="view-stat"><strong>{workspace.graph.nodes.length}</strong> nodes · {workspace.graph.edges.length} edges</span></div><div className="provenance-layout"><section className="card graph-panel"><div className="card-heading"><div><p className="kicker">Interactive graph</p><h2>{selectedNode.size ? 'Focused record' : `Path for ${claim.id}`}</h2></div><button className="secondary-button compact" onClick={() => onNode('')}>Reset path</button></div><EvidenceGraph nodes={workspace.graph.nodes} edges={workspace.graph.edges} selected={effective} onSelect={onNode} /></section>
    <aside className="card node-inspector"><p className="kicker">Record inspector</p>{focused ? <><span className={`node-kind ${focused.kind}`}>{humanize(focused.kind)}</span><h2>{focused.label}</h2><code className="full-digest">{focused.id}</code><div className="connection-list"><span>{connections.length} direct connections</span>{connections.map((edge, index) => <div key={`${edge.source}-${edge.target}-${index}`}><GitBranch size={15} /><span><strong>{humanize(edge.relation)}</strong><small>{shortDigest(edge.source === focused.id ? edge.target : edge.source)}</small></span></div>)}</div>{/^[a-f0-9]{64}$/.test(focused.id) && <a className="primary-button" href={`${API_ROOT}/api/artifacts/${focused.id}`} target="_blank" rel="noreferrer">Open artifact <ArrowRight size={16} /></a>}</> : <div className="empty-result"><Network size={30} /><strong>Select any graph node</strong><p>Its identifier, relationships, and artifact link will appear here.</p></div>}</aside></div></>;
}

function ActivityDock({ workspace }: { workspace: Workspace }) {
  const [expanded, setExpanded] = useState(false);
  const events = expanded ? workspace.events : workspace.events.slice(-6);
  return <section className="activity-dock card"><div className="card-heading"><div><p className="kicker">Saved event replay</p><h2>Orchestration history</h2></div><button className="secondary-button compact" onClick={() => setExpanded(value => !value)}>{expanded ? <Pause size={15} /> : <Activity size={15} />}{expanded ? 'Show recent' : `Show all ${workspace.events.length}`}</button></div><div className="event-track">{events.map(event => <div className="event" key={event.sequence_number}><code>{String(event.sequence_number).padStart(2, '0')}</code><i /><strong>{humanize(event.event_type)}</strong><small>{new Date(event.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</small></div>)}</div></section>;
}

export default function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>('experiment');
  const [selectedClaim, setSelectedClaim] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<Set<string>>(new Set());
  const [selectedPosition, setSelectedPosition] = useState(0);
  const [frameworks, setFrameworks] = useState<ScientificFramework[]>([]);
  useEffect(() => { fetch(`${API_ROOT}/api/workspace`).then(response => { if (!response.ok) throw new Error(`Workspace request failed (${response.status})`); return response.json() as Promise<Workspace>; }).then(setWorkspace).catch(reason => setError(reason instanceof Error ? reason.message : 'Workspace unavailable')); }, []);
  useEffect(() => { fetch(`${API_ROOT}/api/frameworks`).then(response => response.ok ? response.json() as Promise<{ frameworks: ScientificFramework[] }> : Promise.reject(new Error('Framework catalog unavailable'))).then(body => setFrameworks(body.frameworks)).catch(() => undefined); }, []);
  if (error) return <AppLoading error={error} />;
  if (!workspace) return <AppLoading />;
  const claim = workspace.claims.find(item => item.id === selectedClaim) ?? workspace.claims[0];
  const chooseClaim = (id: string) => { const next = workspace.claims.find(item => item.id === id); setSelectedClaim(id); if (next) { setSelectedPosition(next.start); setSelectedNode(pathForClaim(workspace, next)); } };
  const choosePosition = (position: number) => { setSelectedPosition(position); const region = workspace.claims.find(item => position >= item.start && position < item.end); if (region) setSelectedClaim(region.id); };
  return <div className="app-shell"><Sidebar view={view} onView={setView} workspace={workspace} /><main className="workspace-main"><Topbar view={view} workspace={workspace} /><div className="science-notice"><ShieldCheck size={17} /><span><strong>Scientific sandbox.</strong> Live and fixture-backed results are labeled separately; computational output is not biological validation.</span><a href="/privacy">Privacy</a></div>
    {view === 'experiment' && <ExperimentCanvas />}
    {view === 'investigate' && <Investigation workspace={workspace} claim={claim} onClaim={chooseClaim} selectedPosition={selectedPosition} onPosition={position => { choosePosition(position); setView('sandbox'); }} onView={setView} />}
    {view === 'sandbox' && <Sandbox workspace={workspace} position={selectedPosition} onPosition={choosePosition} />}
    {view === 'generate' && <><GenerationPlayground /><ForwardScoringPanel /><ProteinStructurePanel /></>}
    {view === 'antibody' && <AntibodyComplexPanel />}
    {view === 'colony' && <Colony workspace={workspace} />}
    {view === 'provenance' && <Provenance workspace={workspace} claim={claim} selectedNode={selectedNode} onNode={id => setSelectedNode(id ? new Set([id]) : new Set())} />}
    {view === 'frameworks' && <Frameworks frameworks={frameworks} />}
    <ActivityDock workspace={workspace} /><footer><span>Concordia Colony · local-first evidence audit</span><span><Box size={13} /> {workspace.execution_mode.replaceAll('_', ' ')}</span></footer></main></div>;
}
