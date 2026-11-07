import { createClient } from "https://esm.sh/@supabase/supabase-js@2.58.0";

const corsHeaders = {
  "Access-Control-Allow-Origin": "https://concordia.srikarjy.site",
  "Access-Control-Allow-Headers": "authorization, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const sequence = Deno.env.get("CONCORDIA_1IGV_SEQUENCE") ?? "SPEELKGIFEKYAAKEGDPNQLSKEELKLLLQTEFPSLLKGPSTLDELFEELDKNGDGEVSFEEFQVLVKKISQ";
const manifestDigest = Deno.env.get("CONCORDIA_MANIFEST_DIGEST") ?? "";
const scoringUrl = Deno.env.get("THERMOMPNN_URL") ?? "https://srikarjy025-concordia-thermompnn.hf.space";
const ownerUserId = Deno.env.get("CONCORDIA_OWNER_USER_ID") ?? "";
const ownerEmail = (Deno.env.get("CONCORDIA_OWNER_EMAIL") ?? "").trim().toLowerCase();
const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

type Trigger = { code?: string; evidence?: unknown; [key: string]: unknown };
type ScoreReport = { manifest_digest?: string; candidates?: unknown[]; refusals?: unknown[]; [key: string]: unknown };

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { ...corsHeaders, "content-type": "application/json" } });
}

function sha256(value: string): Promise<string> {
  return crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)).then((bytes) =>
    [...new Uint8Array(bytes)].map((v) => v.toString(16).padStart(2, "0")).join("")
  );
}

function safeError(status: number, code: string, message: string) {
  return json({ status: "error", code, message }, status);
}

function mutationSequence(mutation: string): string {
  const match = /^([ACDEFGHIKLMNPQRSTVWY])(\d+)([ACDEFGHIKLMNPQRSTVWY])$/.exec(mutation);
  if (!match) throw new Error("invalid mutation");
  const position = Number(match[2]);
  if (position < 1 || position > sequence.length || sequence[position - 1] !== match[1]) throw new Error("invalid mutation");
  return sequence.slice(0, position - 1) + match[3] + sequence.slice(position);
}

async function nvidia(endpoint: string, payload: unknown, key: string): Promise<{ status: number; body: unknown }> {
  const response = await fetch(endpoint, { method: "POST", headers: { Authorization: `Bearer ${key}`, "content-type": "application/json", Accept: "application/json" }, body: JSON.stringify(payload), signal: AbortSignal.timeout(320_000) });
  const text = await response.text();
  let body: unknown;
  try { body = JSON.parse(text); } catch { body = { raw: "non-json response" }; }
  return { status: response.status, body };
}

function boltzPayload(mutant: string) {
  return { polymers: [{ id: "A", molecule_type: "protein", sequence: mutant, msa: { uniref90: { a3m: { alignment: `>seq1\n${mutant}`, format: "a3m" } } } }], recycling_steps: 1, sampling_steps: 20, diffusion_samples: 1, step_scale: 1.2, without_potentials: true };
}

function openfold3Payload(mutant: string) {
  return { request_id: `concordia-${crypto.randomUUID()}`, inputs: [{ input_id: "1IGV", molecules: [{ type: "protein", id: "A", sequence: mutant, msa: { main_db: { csv: { alignment: `key,sequence\n-1,${mutant}`, format: "csv" } } } }], output_format: "pdb" }] };
}

function extractStructure(operation: string, body: unknown) {
  if (operation === "boltz2" && body && typeof body === "object") {
    const structures = (body as { structures?: unknown }).structures;
    if (Array.isArray(structures) && structures[0] && typeof structures[0] === "object") {
      const first = structures[0] as { structure?: unknown; format?: unknown };
      if (typeof first.structure === "string" && first.structure.length > 0) {
        return { structure_text: first.structure, structure_format: typeof first.format === "string" ? first.format : "pdb" };
      }
    }
  }
  if (operation === "openfold3" && body && typeof body === "object") {
    const outputs = (body as { outputs?: Array<{ structures_with_scores?: Array<{ structure?: string; format?: string }> }> }).outputs;
    const first = outputs?.[0]?.structures_with_scores?.[0];
    if (first?.structure && ['pdb', 'cif', 'mmcif'].includes(first.format ?? '')) return { structure_text: first.structure, structure_format: first.format };
    const value = body as { structure?: unknown; pdb?: unknown; output?: { structure?: unknown; pdb?: unknown } };
    const text = typeof value.structure === "string" ? value.structure : typeof value.pdb === "string" ? value.pdb : typeof value.output?.structure === "string" ? value.output.structure : typeof value.output?.pdb === "string" ? value.output.pdb : null;
    if (text) return { structure_text: text, structure_format: "pdb" };
  }
  return null;
}

async function authenticatedUser(request: Request, admin: ReturnType<typeof createClient>) {
  if (!ownerUserId && !ownerEmail) return null;
  const header = request.headers.get("authorization") ?? "";
  if (!header.startsWith("Bearer ")) return null;
  const { data, error } = await admin.auth.getUser(header.slice(7));
  if (error || !data.user?.email_confirmed_at) return null;
  if (ownerUserId && data.user.id !== ownerUserId) return null;
  if (ownerEmail && (data.user.email ?? "").toLowerCase() !== ownerEmail) return null;
  return data.user;
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (request.method !== "POST") return safeError(405, "METHOD_NOT_ALLOWED", "POST required");
  if (!supabaseUrl || !serviceRoleKey || !manifestDigest) return safeError(503, "NOT_CONFIGURED", "Structure gateway is not configured");
  const admin = createClient(supabaseUrl, serviceRoleKey, { auth: { persistSession: false, autoRefreshToken: false } });
  const user = await authenticatedUser(request, admin);
  if (!user) return safeError(401, "UNAUTHORIZED", "A valid owner session is required");

  let input: { operation?: string; domain?: string; mutations?: unknown; selected_mutation?: string };
  try { input = await request.json(); } catch { return safeError(422, "INVALID_JSON", "Request body must be JSON"); }
  const operation = input.operation;
  if (operation !== "boltz2" && operation !== "openfold3") return safeError(422, "INVALID_OPERATION", "Supported operations are boltz2 and openfold3");
  if (input.domain !== "1IGV" || !Array.isArray(input.mutations) || input.mutations.length < 1 || input.mutations.length > 100 || typeof input.selected_mutation !== "string") return safeError(422, "INVALID_REQUEST", "A 1IGV candidate set and selected mutation are required");
  const mutations = input.mutations.filter((value): value is string => typeof value === "string");
  if (mutations.length !== input.mutations.length) return safeError(422, "INVALID_REQUEST", "Every mutation must be a string");
  const selected = input.selected_mutation;
  if (!mutations.includes(selected)) return safeError(422, "INVALID_SELECTION", "Selected mutation must be in the scored candidate set");
  for (const mutation of mutations) {
    try { for (const part of mutation.split(':')) mutationSequence(part); } catch { return safeError(422, "OUT_OF_RANGE_OR_WRONG_WT", "Mutation failed frozen 1IGV validation"); }
  }

  const scoreResponse = await fetch(`${scoringUrl}/score`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ domain: "1IGV", mutations }), signal: AbortSignal.timeout(180_000) });
  if (!scoreResponse.ok) return safeError(502, "SCORING_UNAVAILABLE", "ThermoMPNN scoring did not complete");
  const scoring = await scoreResponse.json() as ScoreReport;
  if (scoring.manifest_digest !== manifestDigest) return safeError(502, "MANIFEST_MISMATCH", "Scoring response is not from the frozen manifest");
  const selectedId = `1IGV.pdb_${selected}`;
  const refusal = (scoring.refusals ?? []).find((row) => (row as { variant_id?: string }).variant_id === selectedId);
  const accepted = (scoring.candidates ?? []).some((row) => ((row as { candidate?: { variant_id?: string } }).candidate?.variant_id === selectedId));
  if (refusal || !accepted || selected.includes(":")) return json({ status: "refused", operation, stability: scoring, refusal: refusal ?? { variant_id: selectedId, triggers: [{ code: "T3_MULTI_MUTANT_SINGLE_MODEL", evidence: { mutation_count: selected.split(":").length } }] }, hosted_call_made: false });

  const mutant = mutationSequence(selected);
  const cacheKey = await sha256(JSON.stringify({ operation, mutant, manifestDigest, mutations, user: user.id, adapter: 'v2' }));
  const cached = await admin.from("structure_gateway_cache").select("result").eq("cache_key", cacheKey).maybeSingle();
  if (cached.data?.result) return json({ ...cached.data.result, status: "cached", cached: true });
  const quota = await admin.rpc("consume_structure_gateway_quota", { p_user_id: user.id, p_daily_limit: 3 });
  if (quota.error || quota.data !== true) return safeError(429, "QUOTA_EXHAUSTED", "Structure quota reached; scoring remains available");
  const keyResult = await admin.rpc("get_nvidia_api_key");
  const key = keyResult.data as string | null;
  if (keyResult.error || !key) return safeError(503, "PROVIDER_NOT_CONFIGURED", "NVIDIA provider is not configured");
  const endpoint = operation === "boltz2" ? "https://health.api.nvidia.com/v1/biology/mit/boltz2/predict" : "https://health.api.nvidia.com/v1/biology/openfold/openfold3/predict";
  const started = performance.now();
  let provider: { status: number; body: unknown };
  try { provider = await nvidia(endpoint, operation === "boltz2" ? boltzPayload(mutant) : openfold3Payload(mutant), key); } catch { return safeError(502, "PROVIDER_UNAVAILABLE", "NVIDIA structure prediction did not complete"); }
  if (provider.status === 429) return safeError(429, "PROVIDER_RATE_LIMITED", "NVIDIA structure prediction is rate limited");
  if (provider.status < 200 || provider.status >= 300) return safeError(502, "PROVIDER_FAILED", "NVIDIA structure prediction failed");
  const structure = extractStructure(operation, provider.body);
  if (!structure) return safeError(502, "UNPARSEABLE_PROVIDER_RESULT", "NVIDIA returned no supported structure result");
  const providerResponseDigest = await sha256(JSON.stringify(provider.body));
  const result = { status: "completed", operation, model: operation === "boltz2" ? "mit/boltz2" : "openfold/openfold3", stability: scoring, selected_mutation: selected, input_sequence_hash: await sha256(mutant), provider_http_status: provider.status, provider_latency_ms: Math.round(performance.now() - started), provider_response_digest: providerResponseDigest, structure, scope_statement: "Computational structure prediction only; confidence and agreement do not establish folding stability, expression, binding or function." };
  const artifactDigest = await sha256(JSON.stringify(result));
  const output = { ...result, artifact_digest: artifactDigest, cached: false };
  await admin.from("structure_gateway_cache").upsert({ cache_key: cacheKey, operation, result: output }, { onConflict: "cache_key" });
  const run = await admin.from("structure_gateway_runs").insert({ user_id: user.id, operation, request_digest: cacheKey, artifact_digest: artifactDigest, provider_status: provider.status, cached: false }).select("run_id").single();
  let eventError: unknown = null;
  if (run.data?.run_id) {
    const payload = { operation, selected_mutation: selected, artifact_digest: artifactDigest, provider_status: provider.status, cache_key: cacheKey };
    const eventHash = await sha256(JSON.stringify({ prev_hash: "0".repeat(64), run_id: run.data.run_id, sequence_number: 0, event_type: "STRUCTURE_GATEWAY_COMPLETED", payload }));
    const event = await admin.from("structure_gateway_events").insert({ run_id: run.data.run_id, sequence_number: 0, event_type: "STRUCTURE_GATEWAY_COMPLETED", prev_hash: "0".repeat(64), event_hash: eventHash, payload });
    eventError = event.error;
  }
  const finalOutput = { ...output, run_id: run.data?.run_id ?? null, ledger_recorded: Boolean(run.data?.run_id && !run.error && !eventError), ledger_intact: false };
  await admin.from("structure_gateway_cache").update({ result: finalOutput }).eq("cache_key", cacheKey);
  return json(finalOutput);
});
