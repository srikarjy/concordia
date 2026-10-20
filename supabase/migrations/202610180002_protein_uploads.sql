-- Private uploads are available independently of hosted inference permission.
create table public.protein_analyses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  sequence text not null check (sequence ~ '^[ACDEFGHIKLMNPQRSTVWY]{20,300}$'),
  sequence_sha256 text not null check (length(sequence_sha256) = 64),
  created_at timestamptz not null default now(),
  unique(user_id, sequence_sha256)
);
create table public.protein_predictions (
  id uuid primary key default gen_random_uuid(),
  analysis_id uuid not null references public.protein_analyses(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  model text not null check (model in ('boltz2','openfold3')),
  settings_version text not null,
  status text not null check (status in ('running','completed','failed','rate_limited')),
  result jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  unique(analysis_id, model, settings_version)
);
create table public.protein_request_windows (
  user_id uuid not null references auth.users(id) on delete cascade,
  window_start timestamptz not null,
  calls integer not null,
  primary key(user_id, window_start)
);
alter table public.protein_analyses enable row level security;
alter table public.protein_predictions enable row level security;
alter table public.protein_request_windows enable row level security;
revoke all on public.protein_analyses, public.protein_predictions, public.protein_request_windows from public, anon, authenticated;
grant all on public.protein_analyses, public.protein_predictions, public.protein_request_windows to service_role;

-- Fixed limits, no caller-controlled bypass. All three functions are server-only.
create function public.protein_request_allowed(p_user uuid) returns boolean
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  insert into protein_request_windows values (p_user, date_trunc('minute', now()), 1)
  on conflict(user_id, window_start) do update set calls = protein_request_windows.calls + 1
  returning calls into n;
  delete from protein_request_windows where window_start < now() - interval '1 day';
  return n <= 30;
end;
$$;

create function public.save_protein_analysis(p_user uuid, p_sequence text, p_digest text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare a protein_analyses;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_user::text, 0));
  select * into a from protein_analyses where user_id = p_user and sequence_sha256 = p_digest;
  if found then return to_jsonb(a); end if;
  if (select count(*) from protein_analyses where user_id = p_user) >= 20 then
    return jsonb_build_object('error', 'UPLOAD_LIMIT');
  end if;
  insert into protein_analyses(user_id, sequence, sequence_sha256)
  values(p_user, p_sequence, p_digest) returning * into a;
  return to_jsonb(a);
end;
$$;

create function public.reserve_protein_prediction(p_user uuid, p_analysis uuid, p_model text, p_version text, p_global_limit integer)
returns jsonb language plpgsql security definer set search_path = public as $$
declare r protein_predictions;
begin
  -- One transaction serializes reservations; cache hits never consume quota.
  perform pg_advisory_xact_lock(18002026);
  if not exists(select 1 from protein_analyses where id = p_analysis and user_id = p_user) then
    return jsonb_build_object('error','NOT_FOUND');
  end if;
  select * into r from protein_predictions where analysis_id = p_analysis and user_id = p_user and model = p_model and settings_version = p_version;
  if found then return jsonb_build_object('existing',true,'run',to_jsonb(r)); end if;
  if p_global_limit is null or p_global_limit < 1 or p_global_limit > 200 then return jsonb_build_object('error','HOSTED_DISABLED'); end if;
  if (select count(*) from protein_predictions where user_id = p_user and created_at >= date_trunc('day', now() at time zone 'UTC') at time zone 'UTC') >= 2 then
    return jsonb_build_object('error','DAILY_LIMIT');
  end if;
  if (select count(*) from protein_predictions where created_at >= date_trunc('day', now() at time zone 'UTC') at time zone 'UTC') >= p_global_limit then
    return jsonb_build_object('error','GLOBAL_LIMIT');
  end if;
  if exists(select 1 from protein_predictions where user_id = p_user and status = 'running')
    or (select count(*) from protein_predictions where status = 'running') >= 2 then
    return jsonb_build_object('error','BUSY');
  end if;
  insert into protein_predictions(analysis_id,user_id,model,settings_version,status)
  values(p_analysis,p_user,p_model,p_version,'running') returning * into r;
  return jsonb_build_object('existing',false,'run',to_jsonb(r));
end;
$$;
revoke all on function public.protein_request_allowed(uuid), public.save_protein_analysis(uuid,text,text), public.reserve_protein_prediction(uuid,uuid,text,text,integer) from public, anon, authenticated;
grant execute on function public.protein_request_allowed(uuid), public.save_protein_analysis(uuid,text,text), public.reserve_protein_prediction(uuid,uuid,text,text,integer) to service_role;
