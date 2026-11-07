
-- Public portfolio now shows six projects: Aletheia replaces Concordia.
update public.projects
set published = false, updated_at = now()
where slug = 'concordia';

update public.projects
set
  stack = array[
    'Python','FastAPI','React','TypeScript','PostgreSQL','pgvector',
    'Docker','Biolab MCP','LangGraph','LangChain'
  ],
  subtitle = 'Grounded scientific reasoning with LangGraph orchestration and measurable evals',
  updated_at = now()
where slug = 'aletheia';

-- Newsletter subscriptions are server-written only.
create table if not exists public.newsletter_subscribers (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  status text not null default 'active'
    check (status in ('active','unsubscribed')),
  source text not null default 'blog',
  consented_at timestamptz not null default now(),
  unsubscribed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint newsletter_email_normalized_chk
    check (
      email = lower(email)
      and char_length(email) between 3 and 254
      and email ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'
    )
);

create table if not exists public.newsletter_subscription_events (
  id bigint generated always as identity primary key,
  ip_hash text not null,
  attempted_at timestamptz not null default now()
);

create index if not exists newsletter_events_ip_time_idx
  on public.newsletter_subscription_events (ip_hash, attempted_at desc);

alter table public.newsletter_subscribers enable row level security;
alter table public.newsletter_subscribers force row level security;
alter table public.newsletter_subscription_events enable row level security;
alter table public.newsletter_subscription_events force row level security;

revoke all on table public.newsletter_subscribers from public, anon, authenticated;
revoke all on table public.newsletter_subscription_events from public, anon, authenticated;

-- Service role is the only writer used by Vercel server routes.
grant select, insert, update on table public.newsletter_subscribers to service_role;
grant select, insert, delete on table public.newsletter_subscription_events to service_role;

-- Authenticated users may see only the subscription row matching their verified JWT email.
grant select on table public.newsletter_subscribers to authenticated;

drop policy if exists "subscriber can read own row" on public.newsletter_subscribers;
create policy "subscriber can read own row"
on public.newsletter_subscribers
for select
to authenticated
using (
  lower(email) = lower(coalesce(auth.jwt() ->> 'email', ''))
);

-- No anon/authenticated INSERT/UPDATE/DELETE policies intentionally exist.

drop trigger if exists set_newsletter_subscribers_updated_at on public.newsletter_subscribers;
create trigger set_newsletter_subscribers_updated_at
before update on public.newsletter_subscribers
for each row execute function private.set_updated_at();

drop trigger if exists audit_newsletter_subscribers_changes on public.newsletter_subscribers;
create trigger audit_newsletter_subscribers_changes
after insert or update or delete on public.newsletter_subscribers
for each row execute function private.audit_public_content();
;
