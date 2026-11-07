
-- Harden public portfolio content tables.
-- Public clients may SELECT published content only. They cannot mutate rows.

revoke all on table public.projects from public, anon, authenticated;
revoke all on table public.blog_posts from public, anon, authenticated;
revoke all on table public.open_source_contributions from public, anon, authenticated;

grant select on table public.projects to anon, authenticated;
grant select on table public.blog_posts to anon, authenticated;
grant select on table public.open_source_contributions to anon, authenticated;

alter table public.projects force row level security;
alter table public.blog_posts force row level security;
alter table public.open_source_contributions force row level security;

-- Re-create narrowly scoped read policies.
drop policy if exists "public can read published projects" on public.projects;
create policy "public can read published projects"
on public.projects
for select
to anon, authenticated
using (published is true);

drop policy if exists "public can read published blog posts" on public.blog_posts;
create policy "public can read published blog posts"
on public.blog_posts
for select
to anon, authenticated
using (
  published is true
  and published_at is not null
  and published_at <= now()
);

drop policy if exists "public can read published contributions" on public.open_source_contributions;
create policy "public can read published contributions"
on public.open_source_contributions
for select
to anon, authenticated
using (published is true);

-- Private schema is never exposed to PostgREST clients.
create schema if not exists private;
revoke all on schema private from public, anon, authenticated;
grant usage on schema private to postgres;

-- Immutable audit trail for every content mutation.
create table if not exists private.content_audit_log (
  id bigint generated always as identity primary key,
  table_name text not null,
  row_id uuid,
  action text not null check (action in ('INSERT','UPDATE','DELETE')),
  old_row jsonb,
  new_row jsonb,
  changed_at timestamptz not null default now(),
  database_role text not null default current_user,
  jwt_role text,
  jwt_sub text
);

revoke all on table private.content_audit_log from public, anon, authenticated;
revoke update, delete, truncate on table private.content_audit_log from service_role;

create or replace function private.audit_public_content()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public, private
as $$
declare
  v_row_id uuid;
  v_jwt_role text;
  v_jwt_sub text;
begin
  v_jwt_role := nullif(current_setting('request.jwt.claim.role', true), '');
  v_jwt_sub := nullif(current_setting('request.jwt.claim.sub', true), '');

  if tg_op = 'DELETE' then
    v_row_id := old.id;
    insert into private.content_audit_log
      (table_name, row_id, action, old_row, new_row, jwt_role, jwt_sub)
    values
      (tg_table_name, v_row_id, tg_op, to_jsonb(old), null, v_jwt_role, v_jwt_sub);
    return old;
  elsif tg_op = 'UPDATE' then
    v_row_id := new.id;
    insert into private.content_audit_log
      (table_name, row_id, action, old_row, new_row, jwt_role, jwt_sub)
    values
      (tg_table_name, v_row_id, tg_op, to_jsonb(old), to_jsonb(new), v_jwt_role, v_jwt_sub);
    return new;
  else
    v_row_id := new.id;
    insert into private.content_audit_log
      (table_name, row_id, action, old_row, new_row, jwt_role, jwt_sub)
    values
      (tg_table_name, v_row_id, tg_op, null, to_jsonb(new), v_jwt_role, v_jwt_sub);
    return new;
  end if;
end;
$$;

revoke all on function private.audit_public_content() from public, anon, authenticated;

drop trigger if exists audit_projects_changes on public.projects;
create trigger audit_projects_changes
after insert or update or delete on public.projects
for each row execute function private.audit_public_content();

drop trigger if exists audit_blog_posts_changes on public.blog_posts;
create trigger audit_blog_posts_changes
after insert or update or delete on public.blog_posts
for each row execute function private.audit_public_content();

drop trigger if exists audit_open_source_changes on public.open_source_contributions;
create trigger audit_open_source_changes
after insert or update or delete on public.open_source_contributions
for each row execute function private.audit_public_content();

-- Stable upstream contribution identity: sync jobs can update metadata/status,
-- but cannot silently rewrite which upstream PR a row refers to.
create or replace function private.protect_contribution_identity()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public, private
as $$
begin
  if new.external_id is distinct from old.external_id
     or new.repo_owner is distinct from old.repo_owner
     or new.repo_name is distinct from old.repo_name
     or new.pr_number is distinct from old.pr_number then
    raise exception 'open-source contribution identity fields are immutable';
  end if;
  return new;
end;
$$;

revoke all on function private.protect_contribution_identity() from public, anon, authenticated;

drop trigger if exists protect_open_source_identity on public.open_source_contributions;
create trigger protect_open_source_identity
before update on public.open_source_contributions
for each row execute function private.protect_contribution_identity();

-- Ensure timestamps are controlled by the database.
create or replace function private.set_updated_at()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

revoke all on function private.set_updated_at() from public, anon, authenticated;

drop trigger if exists set_projects_updated_at on public.projects;
create trigger set_projects_updated_at
before update on public.projects
for each row execute function private.set_updated_at();

drop trigger if exists set_blog_posts_updated_at on public.blog_posts;
create trigger set_blog_posts_updated_at
before update on public.blog_posts
for each row execute function private.set_updated_at();

drop trigger if exists set_open_source_updated_at on public.open_source_contributions;
create trigger set_open_source_updated_at
before update on public.open_source_contributions
for each row execute function private.set_updated_at();
;
