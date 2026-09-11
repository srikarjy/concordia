export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export interface GraphNode { id: string; label: string; kind: string; layer: number }
export interface Edge { source: string; target: string; relation: string }
export interface EvidenceCheck {
  evidence_id: string; family: string; method: string; assessment: string; valid: boolean;
  source_path: string[]; artifacts_checked: string[]; reasons: string[];
}
export interface Claim {
  id: string; text: string; start: number; end: number; artifact_digest: string;
  verification_digest: string; scope: Record<string, Json>;
  verification: {
    status: string; scientific_use_allowed: boolean; supporting_families: string[];
    contradicting_families: string[]; checks: EvidenceCheck[]; reasons: string[];
  };
  sensitivity?: { count: number; missing_count: number; mean: number; standard_deviation: number; sign_agreement: number };
}
export interface Member {
  member_id: string; generation: number; parent_member_id: string | null;
  genome_digest: string; mutation_digest: string | null; isolation_id: string;
  status: string; output_digest: string | null; terminal_reason: string | null;
  fitness: { weighted_score: number; vector: Record<string, number>; rationale: string[] } | null;
}
export interface RunEvent {
  event_id: string; sequence_number: number; event_type: string;
  created_at: string; payload: Record<string, Json>;
}
export interface Workspace {
  title: string; run_id: string; snapshot_digest: string; execution_mode: string; scientific_use_allowed: boolean;
  sequence: { sequence: string; assembly: string; region: string; strand: string };
  effects: { position: number; reference: string; alternate: string; reference_score: number;
    alternate_score: number; delta: number; reference_artifact_hash: string;
    alternate_artifact_hash: string; scientific_use_allowed: boolean }[];
  claims: Claim[]; graph: { nodes: GraphNode[]; edges: Edge[] }; events: RunEvent[];
  colony: { seed_member: Member; members: Member[]; genomes: Record<string, Json>[];
    mutations: Record<string, Json>[]; selections: {generation: number; survivor_ids: string[]}[] };
  study: { status: string; reason: string; protocol_status: string };
}
