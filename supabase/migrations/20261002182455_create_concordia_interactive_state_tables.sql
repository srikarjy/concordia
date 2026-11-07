
-- Shared persistence for Concordia Colony's interactive NVIDIA-backed endpoints
-- (hosted generation, forward scoring, ESMFold, Boltz-2, colony-run rate limiting).
-- Namespaced by `concordia_` prefix; owned entirely by the Concordia service role,
-- unrelated to the other tables in this project (projects, blog_posts, etc.).

create table if not exists concordia_rate_limit_requests (
    id bigint generated always as identity primary key,
    namespace text not null,
    client_id text not null,
    requested_at double precision not null
);

create index if not exists idx_concordia_rate_limit_lookup
    on concordia_rate_limit_requests (namespace, client_id, requested_at);

create index if not exists idx_concordia_rate_limit_global
    on concordia_rate_limit_requests (namespace, requested_at);

alter table concordia_rate_limit_requests enable row level security;

create table if not exists concordia_result_cache (
    namespace text not null,
    request_key text not null,
    result_json jsonb not null,
    created_at double precision not null,
    primary key (namespace, request_key)
);

alter table concordia_result_cache enable row level security;

create table if not exists concordia_forward_jobs (
    job_id text primary key,
    client_id text not null,
    status text not null,
    submitted_at double precision not null,
    completed_at double precision,
    result_json jsonb,
    error text
);

create index if not exists idx_concordia_forward_jobs_client
    on concordia_forward_jobs (client_id, submitted_at);

alter table concordia_forward_jobs enable row level security;
;
