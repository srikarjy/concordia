import { useEffect, useMemo, useState } from 'react';
import { EvidenceGraph } from './Graph';
import type { Claim, Workspace } from './types';

const API_ROOT = import.meta.env.VITE_API_ROOT ?? '';

function pathForClaim(workspace: Workspace, claim: Claim): Set<string> {
  const ids = new Set<string>([claim.artifact_digest, claim.verification_digest]);
  const walk = (id: string) => {
    workspace.graph.edges.forEach(edge => {
      if (edge.source === id && !ids.has(edge.target)) { ids.add(edge.target); walk(edge.target); }
    });
  };
  walk(claim.artifact_digest);
  return ids;
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

export default function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedClaim, setSelectedClaim] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<Set<string>>(new Set());
  const [eventCursor, setEventCursor] = useState(0);

  useEffect(() => {
    fetch(`${API_ROOT}/api/workspace`)
      .then(response => { if (!response.ok) throw new Error(`workspace request failed (${response.status})`); return response.json() as Promise<Workspace>; })
      .then(setWorkspace)
      .catch(reason => setError(reason instanceof Error ? reason.message : 'workspace unavailable'));
  }, []);

  const claim = workspace?.claims.find(item => item.id === selectedClaim) ?? workspace?.claims[0];
  const highlighted = useMemo(() => claim && workspace ? pathForClaim(workspace, claim) : new Set<string>(), [claim, workspace]);

  if (error) return <main className="shell"><section className="notice"><h1>Concordia Colony</h1><p>{error}</p><p className="muted">Start the read-only workspace API and reload.</p></section></main>;
  if (!workspace) return <main className="shell"><section className="notice"><p>Loading saved scientific workspace…</p></section></main>;

  const visibleEvents = workspace.events.slice(0, eventCursor || workspace.events.length);
  const members = [workspace.colony.seed_member, ...workspace.colony.members];

  return <main className="shell">
    <header className="topbar">
      <div><p className="eyebrow">CONCORDIA COLONY / SCIENTIFIC WORKSPACE</p><h1>{workspace.title}</h1></div>
      <div className="status"><span className="dot" /> saved fixture <code>{workspace.snapshot_digest.slice(0, 12)}</code></div>
    </header>

    <section className="warning"><strong>Software demonstration.</strong> This workspace is fixture-backed; it is not an Evo2 result and cannot support a biological conclusion.</section>

    <section className="metrics panel">
      <Metric label="sequence" value={`${workspace.sequence.sequence.length} bp`} />
      <Metric label="claims" value={workspace.claims.length} />
      <Metric label="colony members" value={members.length} />
      <Metric label="events" value={workspace.events.length} />
      <Metric label="study status" value={workspace.study.status} />
    </section>

    <div className="grid two">
      <section className="panel"><div className="section-head"><div><p className="eyebrow">CLAIM INSPECTOR</p><h2>Evidence-backed questions</h2></div><span className="pill">{claim?.verification.status}</span></div>
        <div className="claim-list">{workspace.claims.map(item => <button key={item.id} className={item.id === claim?.id ? 'claim selected' : 'claim'} onClick={() => { setSelectedClaim(item.id); setSelectedNode(pathForClaim(workspace, item)); }}><span>{item.id}</span><strong>{item.text}</strong><small>{item.start}–{item.end} bp · {item.verification.supporting_families.join(' + ') || 'no independent support'}</small></button>)}</div>
        {claim && <div className="inspector"><p className="eyebrow">SELECTED PATH</p><p>{claim.verification.reasons.join(' ')}</p><div className="checks">{claim.verification.checks.map(check => <div key={check.evidence_id}><span className={check.valid ? 'check ok' : 'check'}>{check.valid ? '✓' : '!'}</span><span><strong>{check.family}</strong><small>{check.method} · {check.reasons.join(' ')}</small></span></div>)}</div></div>}
      </section>
      <section className="panel"><div className="section-head"><div><p className="eyebrow">COLONY LINEAGE</p><h2>Workflow descendants</h2></div><span className="pill">2 generations</span></div>
        <div className="lineage">{members.map(member => <button key={member.member_id} className={member.member_id === claim?.id ? 'member selected' : 'member'} onClick={() => setSelectedNode(new Set([member.genome_digest, ...(member.mutation_digest ? [member.mutation_digest] : [])]))}><span className={`member-status ${member.status.toLowerCase()}`} /> <span><strong>{member.member_id}</strong><small>generation {member.generation} · {member.status}{member.fitness ? ` · fitness ${member.fitness.weighted_score.toFixed(3)}` : ''}</small></span></button>)}</div>
      </section>
    </div>

    <section className="panel"><div className="section-head"><div><p className="eyebrow">SEQUENCE / COUNTERFACTUAL TRACK</p><h2>{workspace.sequence.region}</h2></div><span className="pill">zero-based · strand {workspace.sequence.strand}</span></div>
      <div className="sequence" aria-label="Sequence and mutational scan track"><div className="bases">{workspace.sequence.sequence.split('').map((base, index) => <span key={index} title={`position ${index}`}>{base}</span>)}</div><div className="bars">{workspace.effects.map(effect => <span key={effect.position} style={{ height: `${Math.max(8, Math.min(100, Math.abs(effect.delta) * 1000))}%` }} className={effect.delta < 0 ? 'negative' : ''} title={`position ${effect.position}: Δ ${effect.delta.toFixed(5)}`} />)}</div><div className="axis"><span>0</span><span>{workspace.sequence.sequence.length / 2}</span><span>{workspace.sequence.sequence.length}</span></div></div>
    </section>

    <section className="panel"><div className="section-head"><div><p className="eyebrow">KNOWLEDGE / PROVENANCE GRAPH</p><h2>Click a node to illuminate its path</h2></div><button className="text-button" onClick={() => setSelectedNode(new Set())}>clear focus</button></div><EvidenceGraph nodes={workspace.graph.nodes} edges={workspace.graph.edges} selected={highlighted.size ? highlighted : selectedNode} onSelect={id => setSelectedNode(new Set([id]))} /></section>

    <section className="panel"><div className="section-head"><div><p className="eyebrow">LIVE EVENT REPLAY</p><h2>Saved orchestration history</h2></div><button className="text-button" onClick={() => setEventCursor(eventCursor ? 0 : Math.min(10, workspace.events.length))}>{eventCursor ? 'show all' : 'pause playback'}</button></div><div className="events">{visibleEvents.map(event => <div className="event" key={event.sequence_number}><code>#{event.sequence_number}</code><strong>{event.event_type}</strong><small>{new Date(event.created_at).toLocaleTimeString()}</small></div>)}</div></section>

    <footer><span>Concordia Colony · local-first provenance audit</span><span>fixture mode · scientific use prohibited</span></footer>
  </main>;
}
