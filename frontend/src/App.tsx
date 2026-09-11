import { useEffect, useMemo, useState } from 'react';
import {
  Activity, ArrowRight, Box, CheckCircle2, ChevronRight, CircleHelp, Dna,
  FlaskConical, GitBranch, Network, Pause, Play, RotateCcw, Search,
  ShieldCheck, Sparkles, XCircle,
} from 'lucide-react';
import { EvidenceGraph } from './Graph';
import type { Claim, EvidenceCheck, Member, Workspace } from './types';

const API_ROOT = import.meta.env.VITE_API_ROOT ?? '';
const BASES = ['A', 'C', 'G', 'T'];
type View = 'investigate' | 'sandbox' | 'colony' | 'provenance';

const NAV_ITEMS: { id: View; label: string; description: string; icon: typeof Search }[] = [
  { id: 'investigate', label: 'Investigation', description: 'Claims and evidence', icon: Search },
  { id: 'sandbox', label: 'Sequence sandbox', description: 'Replay perturbations', icon: FlaskConical },
  { id: 'colony', label: 'Colony evolution', description: 'Lineage and fitness', icon: GitBranch },
  { id: 'provenance', label: 'Provenance graph', description: 'Trace every artifact', icon: Network },
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
    <div className="boundary-card"><div><ShieldCheck size={18} /><strong>Scientific boundary</strong></div><p>This public workspace replays saved software fixtures. It never runs Evo2 or claims biological support.</p><span><i /> No data leaves this page</span></div>
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

function FitnessBars({ member }: { member: Member }) {
  if (!member.fitness) return <div className="empty-inline">The seed has no fitness measurement.</div>;
  const entries = Object.entries(member.fitness.vector).filter(([, value]) => typeof value === 'number').slice(0, 9);
  return <div className="fitness-bars">{entries.map(([label, value]) => { const normalized = label.includes('runtime') || label.includes('usage') ? Math.min(1, value / 200) : Math.min(1, Math.max(0, value)); return <div key={label}><span>{humanize(label)}</span><div><i style={{ width: `${normalized * 100}%` }} /></div><strong>{value.toFixed(value < 10 ? 3 : 0)}</strong></div>; })}</div>;
}

function Colony({ workspace }: { workspace: Workspace }) {
  const members = [workspace.colony.seed_member, ...workspace.colony.members];
  const maxGeneration = Math.max(...members.map(member => member.generation));
  const [generation, setGeneration] = useState(maxGeneration);
  const visible = members.filter(member => member.generation <= generation);
  const [selectedId, setSelectedId] = useState(visible.at(-1)?.member_id ?? members[0].member_id);
  const selected = members.find(member => member.member_id === selectedId) ?? members[0];
  const fallbackId = visible.at(-1)?.member_id ?? members[0].member_id;
  useEffect(() => {
    if (selected.generation > generation) setSelectedId(fallbackId);
  }, [fallbackId, generation, selected.generation]);
  const survivors = new Set(workspace.colony.selections.flatMap(selection => selection.survivor_ids));
  return <><div className="view-intro"><div><p className="kicker">Evolution audit</p><h2>Scrub through generations and inspect why workflows survived.</h2></div><span className="view-stat"><strong>{members.length}</strong> total members</span></div><section className="card generation-control"><div><span>Seed</span><strong>Generation {generation}</strong><span>Generation {maxGeneration}</span></div><input aria-label="Generation" type="range" min="0" max={maxGeneration} value={generation} onChange={event => setGeneration(Number(event.target.value))} /><div className="generation-dots">{Array.from({ length: maxGeneration + 1 }, (_, index) => <button aria-label={`Show generation ${index}`} key={index} className={index <= generation ? 'active' : ''} onClick={() => setGeneration(index)} />)}</div></section>
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
  const [view, setView] = useState<View>('investigate');
  const [selectedClaim, setSelectedClaim] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<Set<string>>(new Set());
  const [selectedPosition, setSelectedPosition] = useState(0);
  useEffect(() => { fetch(`${API_ROOT}/api/workspace`).then(response => { if (!response.ok) throw new Error(`Workspace request failed (${response.status})`); return response.json() as Promise<Workspace>; }).then(setWorkspace).catch(reason => setError(reason instanceof Error ? reason.message : 'Workspace unavailable')); }, []);
  if (error) return <AppLoading error={error} />;
  if (!workspace) return <AppLoading />;
  const claim = workspace.claims.find(item => item.id === selectedClaim) ?? workspace.claims[0];
  const chooseClaim = (id: string) => { const next = workspace.claims.find(item => item.id === id); setSelectedClaim(id); if (next) { setSelectedPosition(next.start); setSelectedNode(pathForClaim(workspace, next)); } };
  const choosePosition = (position: number) => { setSelectedPosition(position); const region = workspace.claims.find(item => position >= item.start && position < item.end); if (region) setSelectedClaim(region.id); };
  return <div className="app-shell"><Sidebar view={view} onView={setView} workspace={workspace} /><main className="workspace-main"><Topbar view={view} workspace={workspace} /><div className="science-notice"><ShieldCheck size={17} /><span><strong>Software demonstration.</strong> Every result is fixture-backed and cannot support a biological conclusion.</span><a href="/api/report">Read report</a></div>
    {view === 'investigate' && <Investigation workspace={workspace} claim={claim} onClaim={chooseClaim} selectedPosition={selectedPosition} onPosition={position => { choosePosition(position); setView('sandbox'); }} onView={setView} />}
    {view === 'sandbox' && <Sandbox workspace={workspace} position={selectedPosition} onPosition={choosePosition} />}
    {view === 'colony' && <Colony workspace={workspace} />}
    {view === 'provenance' && <Provenance workspace={workspace} claim={claim} selectedNode={selectedNode} onNode={id => setSelectedNode(id ? new Set([id]) : new Set())} />}
    <ActivityDock workspace={workspace} /><footer><span>Concordia Colony · local-first evidence audit</span><span><Box size={13} /> {workspace.execution_mode.replaceAll('_', ' ')}</span></footer></main></div>;
}
