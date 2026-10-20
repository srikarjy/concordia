import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.58.0';
import { parseProtein, parsedStructure, SETTINGS_VERSION, SCOPE } from './contract.ts';

const headers = { 'Access-Control-Allow-Origin': 'https://concordia.srikarjy.site', 'Access-Control-Allow-Headers': 'authorization, content-type, apikey, x-client-info', 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Content-Type': 'application/json', 'Cache-Control': 'no-store' };
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers });
const fail = (code: string, message: string, status = 400) => reply({ code, message }, status);
const digest = async (value: string) => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))].map(x => x.toString(16).padStart(2, '0')).join('');
const globalLimit = Number(Deno.env.get('CONCORDIA_PUBLIC_DAILY_LIMIT') ?? '0');
const enabled = Deno.env.get('CONCORDIA_PUBLIC_NVIDIA_APPROVED') === 'true' && Number.isInteger(globalLimit) && globalLimit > 0 && globalLimit <= 200;

Deno.serve(async request => {
  if (request.method === 'OPTIONS') return new Response(null, { headers });
  if (request.method !== 'POST') return fail('METHOD', 'POST required', 405);
  try {
    const admin = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
    const bearer = request.headers.get('authorization')?.match(/^Bearer (.+)$/)?.[1];
    if (!bearer) return fail('UNAUTHORIZED', 'Sign in with a verified email.', 401);
    const { data, error } = await admin.auth.getUser(bearer);
    if (error || !data.user?.email_confirmed_at || data.user.is_anonymous) return fail('UNAUTHORIZED', 'Sign in with a verified email.', 401);
    const user = data.user.id;
    const rate = await admin.rpc('protein_request_allowed', { p_user: user });
    if (rate.error) return fail('DATABASE', 'Request accounting is unavailable.', 503);
    if (!rate.data) return fail('REQUEST_LIMIT', 'Thirty requests per minute allowed. Try again in one minute.', 429);
    // Bound the streamed body rather than trusting Content-Length.
    const reader = request.body?.getReader();
    if (!reader) return fail('BODY', 'JSON request required.');
    const chunks: Uint8Array[] = []; let bytes = 0;
    while (true) {
      const part = await reader.read(); if (part.done) break;
      bytes += part.value.length;
      if (bytes > 16384) { await reader.cancel(); return fail('BODY_SIZE', 'Request exceeds 16 KB.', 413); }
      chunks.push(part.value);
    }
    const raw = new Uint8Array(bytes); let offset = 0;
    for (const part of chunks) { raw.set(part, offset); offset += part.length; }
    let input: Record<string, unknown>;
    try { input = JSON.parse(new TextDecoder().decode(raw)); } catch { return fail('JSON', 'Invalid JSON.'); }
    if (!input || typeof input !== 'object') return fail('JSON', 'JSON object required.');
    if (input.action === 'list') {
      const analyses = await admin.from('protein_analyses').select('*').eq('user_id', user).order('created_at', { ascending: false });
      const runs = await admin.from('protein_predictions').select('id,analysis_id,model,status,created_at,completed_at').eq('user_id', user).order('created_at', { ascending: false });
      if (analyses.error || runs.error) return fail('DATABASE', 'History unavailable.', 503);
      const today = new Date().toISOString().slice(0, 10);
      return reply({ user_id: user, analyses: analyses.data, runs: runs.data, remaining: Math.max(0, 2 - runs.data.filter(r => r.created_at.startsWith(today)).length), resets_at: new Date(Date.parse(today) + 86400000).toISOString(), hosted_enabled: enabled, scope_statement: SCOPE });
    }
    if (input.action === 'upload') {
      let sequence: string;
      try { sequence = parseProtein(input.sequence); } catch (e) { return fail('INVALID_PROTEIN', (e as Error).message, 422); }
      const saved = await admin.rpc('save_protein_analysis', { p_user: user, p_sequence: sequence, p_digest: await digest(sequence) });
      if (saved.error) return fail('DATABASE', 'Upload could not be saved.', 503);
      if (saved.data.error) return fail('UPLOAD_LIMIT', 'Maximum twenty saved proteins per account.', 429);
      return reply({ analysis: saved.data, scope_statement: SCOPE }, 201);
    }
    const id = input.action === 'result' ? input.run_id : input.analysis_id;
    if (typeof id !== 'string' || !/^[a-f0-9-]{36}$/i.test(id)) return fail('ID', 'A valid analysis or run ID is required.', 422);
    if (input.action === 'result') {
      const run = await admin.from('protein_predictions').select('id,analysis_id,model,status,result,created_at,completed_at').eq('id', id).eq('user_id', user).maybeSingle();
      if (run.error) return fail('DATABASE', 'Result unavailable.', 503);
      return run.data ? reply(run.data) : fail('NOT_FOUND', 'Result not found.', 404);
    }
    if (input.action !== 'predict' || !['boltz2','openfold3'].includes(String(input.model))) return fail('ACTION', 'Choose upload, list, result or predict with a supported model.', 422);
    const analysis = await admin.from('protein_analyses').select('*').eq('id', id).eq('user_id', user).maybeSingle();
    if (analysis.error) return fail('DATABASE', 'Upload unavailable.', 503);
    if (!analysis.data) return fail('NOT_FOUND', 'Upload not found.', 404);
    if (!enabled) return fail('HOSTED_ACCESS_PENDING', 'Protein upload is available. Public predictions await a production-authorized NVIDIA service and verified credit budget. No model call was made.', 403);
    if (input.provider_consent !== true) return fail('CONSENT', 'Confirm sending this non-confidential sequence to NVIDIA.', 422);
    const reservation = await admin.rpc('reserve_protein_prediction', { p_user: user, p_analysis: id, p_model: input.model, p_version: SETTINGS_VERSION, p_global_limit: globalLimit });
    if (reservation.error) return fail('DATABASE', 'Quota reservation failed.', 503);
    if (reservation.data.error) return fail(reservation.data.error, 'Prediction limit reached or another prediction is active. No provider call was made.', 429);
    const run = reservation.data.run;
    if (reservation.data.existing) return reply({ ...run, cached: run.status === 'completed' });
    let result: Record<string, unknown>; let status = 'failed';
    try {
      const secret = await admin.rpc('get_nvidia_api_key');
      if (secret.error || typeof secret.data !== 'string' || !secret.data) throw new Error('PROVIDER_NOT_CONFIGURED');
      const seq = analysis.data.sequence;
      const payload = input.model === 'boltz2'
        ? { polymers: [{ id: 'A', molecule_type: 'protein', sequence: seq, msa: { uniref90: { a3m: { alignment: `>query\n${seq}`, format: 'a3m' } } } }], recycling_steps: 1, sampling_steps: 20, diffusion_samples: 1, step_scale: 1.2, without_potentials: true }
        : { request_id: run.id, inputs: [{ input_id: id, output_format: 'pdb', molecules: [{ type: 'protein', id: 'A', sequence: seq, msa: { main_db: { csv: { alignment: `key,sequence\n-1,${seq}`, format: 'csv' } } } }] }] };
      const endpoint = input.model === 'boltz2' ? 'https://health.api.nvidia.com/v1/biology/mit/boltz2/predict' : 'https://health.api.nvidia.com/v1/biology/openfold/openfold3/predict';
      const start = performance.now();
      const response = await fetch(endpoint, { method: 'POST', headers: { Authorization: `Bearer ${secret.data}`, 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(payload), signal: AbortSignal.timeout(90000) });
      if (response.status !== 200) {
        status = response.status === 429 ? 'rate_limited' : 'failed';
        result = { code: response.status === 202 ? 'ASYNC_UNSUPPORTED' : 'PROVIDER_FAILED', http_status: response.status, message: 'Provider did not return a completed structure. No automatic retry was made.' };
      } else {
        const body = await response.json();
        const structure = parsedStructure(String(input.model), body);
        const artifact = { structure, model: input.model, settings_version: SETTINGS_VERSION, sequence_sha256: analysis.data.sequence_sha256, request: payload, response_sha256: await digest(JSON.stringify(body)), latency_ms: Math.round(performance.now() - start), http_status: 200, msa: 'query-only; no evolutionary search', scope_statement: SCOPE };
        result = { ...artifact, artifact_digest: await digest(JSON.stringify(artifact)), ledger_status: 'recorded; no verified ledger chain' };
        status = 'completed';
      }
    } catch { result = { code: 'PROVIDER_UNAVAILABLE', message: 'Prediction did not complete or returned an unsupported structure. No automatic retry was made.' }; }
    const finished = await admin.from('protein_predictions').update({ status, result, completed_at: new Date().toISOString() }).eq('id', run.id).eq('user_id', user).select('id,analysis_id,model,status,result,created_at,completed_at').single();
    if (finished.error) return fail('PERSISTENCE_FAILED', `Result could not be saved. Reference run ${run.id}; do not resubmit.`, 503);
    return reply(finished.data);
  } catch { return fail('UNAVAILABLE', 'The protein workspace is temporarily unavailable.', 503); }
});
