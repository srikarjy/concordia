create table if not exists public.structure_gateway_cache (
  cache_key text primary key,
  operation text not null check (operation in ('boltz2', 'openfold3')),
  result jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists public.structure_gateway_usage (
  user_id uuid not null,
  window_start date not null,
  calls integer not null default 0 check (calls >= 0),
  primary key (user_id, window_start)
);

create table if not exists public.structure_gateway_runs (
  run_id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  operation text not null,
  request_digest text not null,
  artifact_digest text not null unique,
  provider_status integer,
  cached boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists public.structure_gateway_events (
  run_id uuid not null references public.structure_gateway_runs(run_id) on delete cascade,
  sequence_number integer not null,
  event_type text not null,
  prev_hash text not null,
  event_hash text not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  primary key (run_id, sequence_number)
);

alter table public.structure_gateway_cache enable row level security;
alter table public.structure_gateway_usage enable row level security;
alter table public.structure_gateway_runs enable row level security;
alter table public.structure_gateway_events enable row level security;

revoke all on public.structure_gateway_cache from anon, authenticated;
revoke all on public.structure_gateway_usage from anon, authenticated;
revoke all on public.structure_gateway_runs from anon, authenticated;
revoke all on public.structure_gateway_events from anon, authenticated;

create or replace function public.consume_structure_gateway_quota(
  p_user_id uuid,
  p_daily_limit integer default 3
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  current_calls integer;
begin
  insert into public.structure_gateway_usage(user_id, window_start, calls)
  values (p_user_id, current_date, 0)
  on conflict (user_id, window_start) do nothing;

  select calls into current_calls
  from public.structure_gateway_usage
  where user_id = p_user_id and window_start = current_date
  for update;

  if current_calls >= p_daily_limit then
    return false;
  end if;

  update public.structure_gateway_usage
  set calls = calls + 1
  where user_id = p_user_id and window_start = current_date;
  return true;
end;
$$;

revoke all on function public.consume_structure_gateway_quota(uuid, integer) from public, anon, authenticated;
grant execute on function public.consume_structure_gateway_quota(uuid, integer) to service_role;

create or replace function public.get_nvidia_api_key()
returns text
language sql
security definer
set search_path = public, vault
as $$
  select decrypted_secret
  from vault.decrypted_secrets
  where name = 'NVIDIA_API_KEY'
  order by updated_at desc
  limit 1;
$$;

revoke all on function public.get_nvidia_api_key() from public, anon, authenticated;
grant execute on function public.get_nvidia_api_key() to service_role;
