-- Run once in Supabase: SQL Editor -> New query -> paste -> Run.
create table if not exists public.reviews (
  email_id   text primary key,
  review     jsonb not null,
  updated_at timestamptz not null default now()
);

-- Row-level security on with no policies: the public anon key can read and write nothing.
-- The server uses the service-role key, which bypasses RLS.
alter table public.reviews enable row level security;
