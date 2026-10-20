
-- Defense-in-depth constraints for externally sourced / URL-derived values.
-- These are integrity controls in addition to parameterized Supabase/PostgREST access.

alter table public.projects
  add constraint projects_slug_safe_chk
  check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$') not valid;

alter table public.blog_posts
  add constraint blog_posts_slug_safe_chk
  check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$') not valid;

alter table public.projects
  add constraint projects_text_lengths_chk
  check (
    char_length(name) between 1 and 120
    and char_length(subtitle) between 1 and 240
    and char_length(summary) between 1 and 3000
  ) not valid;

alter table public.blog_posts
  add constraint blog_posts_text_lengths_chk
  check (
    char_length(title) between 1 and 240
    and char_length(excerpt) between 1 and 1000
    and char_length(body_md) between 1 and 200000
  ) not valid;

alter table public.open_source_contributions
  add constraint osc_repo_owner_safe_chk
  check (repo_owner ~ '^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$') not valid;

alter table public.open_source_contributions
  add constraint osc_repo_name_safe_chk
  check (repo_name ~ '^[A-Za-z0-9._-]{1,100}$') not valid;

alter table public.open_source_contributions
  add constraint osc_pr_number_positive_chk
  check (pr_number > 0) not valid;

alter table public.open_source_contributions
  add constraint osc_github_url_chk
  check (url ~ '^https://github\.com/[^/]+/[^/]+/pull/[0-9]+$') not valid;

alter table public.open_source_contributions
  add constraint osc_external_id_consistency_chk
  check (external_id = repo_owner || '/' || repo_name || '#' || pr_number::text) not valid;

-- Validate after creation so existing data is checked explicitly.
alter table public.projects validate constraint projects_slug_safe_chk;
alter table public.blog_posts validate constraint blog_posts_slug_safe_chk;
alter table public.projects validate constraint projects_text_lengths_chk;
alter table public.blog_posts validate constraint blog_posts_text_lengths_chk;
alter table public.open_source_contributions validate constraint osc_repo_owner_safe_chk;
alter table public.open_source_contributions validate constraint osc_repo_name_safe_chk;
alter table public.open_source_contributions validate constraint osc_pr_number_positive_chk;
alter table public.open_source_contributions validate constraint osc_github_url_chk;
alter table public.open_source_contributions validate constraint osc_external_id_consistency_chk;

-- Explicitly deny executable public API functions unless deliberately granted later.
revoke execute on all functions in schema public from public, anon, authenticated;
;
