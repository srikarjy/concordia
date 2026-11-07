import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';

type Evidence = {
  run_id: string;
  model_id: string;
  model_version: string;
  verification_status: 'supported' | 'unverifiable' | 'refused';
  verification_reasons: string[];
  params_hash: string | null;
  created_at: string;
};

type Ledger = {
  runs_checked: number;
  events_checked: number;
  breaks: string[];
  intact: boolean;
  heads: Record<string, string>;
};

type Stability = {
  candidates: Array<{ candidate: { variant_id: string }; rank: number }>;
  refusals: Array<{ variant_id: string; triggers: Array<{ code: string; reason?: string; accession?: string; feature_type?: string; uniprot_position?: number; mutation_count?: number }> }>;
  artifact_digest: string;
};

type Execution = {
  dataset_rows: number;
  train_rows: number;
  test_rows: number;
  ridge_rmse: number;
  mean_baseline_rmse: number;
  scripted_decisions: Record<string, string>;
};

type Snapshot = { evidence: Evidence[]; ledger: Ledger; stability: Stability; execution: Execution };

const bg = '#07110f';
const panel = '#101d1a';
const border = '#263a34';
const muted = '#98aaa3';
const ink = '#edf5f0';
const green = '#4fe0a0';

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    async function load() {
      try {
        const [evidenceResponse, ledgerResponse, stabilityResponse, executionResponse] = await Promise.all([
          fetch('/data/model-run-evidence.jsonl'),
          fetch('/data/ledger-summary.json'),
          fetch('/data/stability.json'),
          fetch('/public-data-review/execution.json'),
        ]);
        for (const response of [evidenceResponse, ledgerResponse, stabilityResponse, executionResponse]) {
          if (!response.ok) throw new Error(`Could not load ${response.url} (${response.status})`);
        }
        const lines = (await evidenceResponse.text()).trim().split('\n').filter(Boolean);
        const [ledger, stability, execution] = await Promise.all([
          ledgerResponse.json() as Promise<Ledger>,
          stabilityResponse.json() as Promise<Stability>,
          executionResponse.json() as Promise<Execution>,
        ]);
        setSnapshot({ evidence: lines.map((line) => JSON.parse(line) as Evidence), ledger, stability, execution });
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Snapshot could not be loaded');
      }
    }
    void load();
  }, []);

  const section: React.CSSProperties = { background: panel, border: `1px solid ${border}`, borderRadius: 16, padding: 24, marginTop: 16 };
  const label: React.CSSProperties = { color: muted, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.12em' };
  const value: React.CSSProperties = { color: ink, fontSize: 24, fontWeight: 700, marginTop: 6 };
  const hashShort = (hash: string) => `${hash.slice(0, 12)}…`;

  return (
    <main style={{ background: bg, color: ink, minHeight: '100vh', fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif', padding: '36px 20px 28px' }}>
      <div style={{ maxWidth: 1040, margin: '0 auto' }}>
        <header style={{ padding: '12px 2px 8px' }}>
          <div style={{ ...label, color: green }}>CONCORDIA / SCIENTIFIC SOFTWARE</div>
          <h1 style={{ fontSize: 'clamp(30px, 5vw, 48px)', letterSpacing: '-0.04em', margin: '12px 0 8px' }}>Evidence workspace for protein variants</h1>
          <p style={{ color: muted, margin: 0 }}>In-silico only. No biological validation.</p>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 18 }}>
            {['603 tests', 'Committed hashes verified', 'Negative results named'].map((item) => <span key={item} style={{ border: `1px solid ${border}`, borderRadius: 999, color: '#c7d7cf', padding: '7px 12px', fontSize: 13 }}>{item}</span>)}
          </div>
        </header>

        {error && <div role="alert" style={{ ...section, borderColor: '#a64848', color: '#ffb9b9' }}>Snapshot load error: {error}</div>}
        {!snapshot && !error && <div style={{ ...section, color: muted }}>Loading committed evidence snapshot…</div>}

        {snapshot && <>
          <section style={section} aria-labelledby="ledger-title">
            <div style={label}>01 / Provenance</div>
            <h2 id="ledger-title" style={{ margin: '7px 0 18px', fontSize: 21 }}>Hash-chained ledger</h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(135px, 1fr))', gap: 12 }}>
              {[['Runs checked', snapshot.ledger.runs_checked], ['Events checked', snapshot.ledger.events_checked], ['Breaks', snapshot.ledger.breaks.length], ['Integrity', snapshot.ledger.intact ? '✓ intact' : 'broken']].map(([key, val]) => (
                <div key={key} style={{ border: `1px solid ${border}`, borderRadius: 12, padding: 14 }}><div style={label}>{key}</div><div style={{ ...value, color: key === 'Integrity' && snapshot.ledger.intact ? green : ink, fontSize: 21 }}>{val}</div></div>
              ))}
            </div>
            <div style={{ marginTop: 16, display: 'grid', gap: 8 }}>
              {Object.entries(snapshot.ledger.heads).map(([run, hash]) => <div key={run} title={hash} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, color: muted, fontSize: 13 }}><span>{run}</span><code style={{ color: '#c4d8cf' }}>{hashShort(hash)}</code></div>)}
            </div>
          </section>

          <section style={section} aria-labelledby="evidence-title">
            <div style={label}>02 / Model-run records</div>
            <h2 id="evidence-title" style={{ margin: '7px 0 18px', fontSize: 21 }}>Evidence and provenance limits</h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(245px, 1fr))', gap: 12 }}>
              {snapshot.evidence.map((record) => <article key={record.run_id} style={{ border: `1px solid ${border}`, borderRadius: 13, padding: 17, minWidth: 0 }}>
                <h3 style={{ fontSize: 17, margin: '0 0 8px', overflowWrap: 'anywhere' }}>{record.model_id}</h3>
                <div style={{ color: muted, fontSize: 12, marginBottom: 12 }}>{record.model_version}</div>
                <span style={{ display: 'inline-block', border: `1px solid ${record.verification_status === 'supported' ? green : '#d69b4d'}`, color: record.verification_status === 'supported' ? green : '#f0bd72', borderRadius: 999, padding: '4px 9px', fontSize: 12 }}>{record.verification_status}</span>
                <div style={{ marginTop: 12, fontSize: 13 }}><span style={{ color: muted }}>params: </span>{record.params_hash ? <code>{record.params_hash.slice(0, 12)}…</code> : <strong style={{ color: '#ff746c', letterSpacing: '0.04em' }}>NOT RECORDED</strong>}</div>
                <ul style={{ color: '#c5d2cc', fontSize: 12, lineHeight: 1.5, paddingLeft: 18, margin: '11px 0' }}>{record.verification_reasons.length ? record.verification_reasons.map((reason) => <li key={reason}>{reason}</li>) : <li>—</li>}</ul>
                <div style={{ color: muted, fontSize: 12 }}>{record.created_at}</div>
              </article>)}
            </div>
          </section>

          <section style={section} aria-labelledby="pga-title">
            <div style={label}>03 / Measured-data review</div>
            <h2 id="pga-title" style={{ margin: '7px 0 8px', fontSize: 21 }}>1PGA · retrospective stability benchmark</h2>
            <p style={{ color: muted, margin: '0 0 16px' }}>{snapshot.execution.dataset_rows} variants · {snapshot.execution.train_rows} train / {snapshot.execution.test_rows} held out · RMSE {snapshot.execution.ridge_rmse.toFixed(3)} vs {snapshot.execution.mean_baseline_rmse.toFixed(3)} baseline</p>
            <div style={{ color: '#c5d2cc', fontSize: 14 }}>Decisions: {Object.entries(snapshot.execution.scripted_decisions).map(([variant, decision]) => <span key={variant} style={{ marginRight: 12 }}>{variant} <b style={{ color: ink }}>{decision}</b></span>)}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', marginTop: 18 }}>
              <code style={{ color: '#c5d2cc' }}>Bundle SHA-256: b620326b949224487233cd7d89308a393acb14981d625d87f99ce05bf23c2bdb</code>
              <a href="/public-data-review/bundle.zip" download style={{ color: green, fontWeight: 700 }}>Download bundle →</a>
            </div>
          </section>

          <section style={section} aria-labelledby="igv-title">
            <div style={label}>04 / Typed stability review</div>
            <h2 id="igv-title" style={{ margin: '7px 0 12px', fontSize: 21 }}>1IGV · position-held-out ranker</h2>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 15 }}>{snapshot.stability.candidates.sort((a, b) => a.rank - b.rank).map((candidate) => <span key={candidate.candidate.variant_id} style={{ border: `1px solid ${border}`, borderRadius: 9, padding: '8px 11px' }}>Rank {candidate.rank}: <b>{candidate.candidate.variant_id.split('_').pop()}</b></span>)}</div>
            <div style={{ color: '#c5d2cc', lineHeight: 1.7, marginTop: 12 }}>
              <b style={{ display: 'block', marginBottom: 7 }}>Refused</b>
              {snapshot.stability.refusals.map((item) => <div key={item.variant_id} style={{ borderLeft: '2px solid #d69b4d', paddingLeft: 11, marginBottom: 10 }}>
                <b>{item.variant_id.split('_').pop()}</b>
                {item.triggers.map((trigger) => {
                  const context = trigger.reason ?? ([
                    trigger.feature_type,
                    trigger.accession,
                    trigger.uniprot_position === undefined ? undefined : `UniProt position ${trigger.uniprot_position}`,
                    trigger.mutation_count === undefined ? undefined : `${trigger.mutation_count} mutations`,
                  ].filter(Boolean).join(' · ') || '—');
                  return <div key={trigger.code} style={{ fontSize: 13 }}><code style={{ color: '#f0bd72' }}>{trigger.code}</code><span style={{ color: muted }}> — {context}</span></div>;
                })}
              </div>)}
            </div>
            <div style={{ color: muted, fontSize: 13, marginTop: 8 }}>Static artifact digest: <code style={{ color: '#c5d2cc' }}>{snapshot.stability.artifact_digest}</code></div>
          </section>

          <footer style={{ borderTop: `1px solid ${border}`, marginTop: 20, padding: '18px 2px 0', color: muted, fontSize: 13 }}>
            4 emitters. 3 unverifiable because sources don’t record params — validator enforces this. 4 more scaffolds need live execution, not fabrication.
          </footer>
        </>}
      </div>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
