-- Athar Supabase schema capability marker.
-- Safe to rerun after the editor, atomic-publish, and layout migrations.

create table if not exists public.athar_schema_versions (
  component text primary key,
  version integer not null check (version > 0),
  updated_at timestamptz not null default now()
);

insert into public.athar_schema_versions (component, version, updated_at)
values
  ('editor', 5, now()),
  ('layout', 2, now())
on conflict (component) do update
set version = greatest(athar_schema_versions.version, excluded.version),
    updated_at = excluded.updated_at;

alter table public.athar_schema_versions enable row level security;
revoke all on table public.athar_schema_versions from anon, authenticated;
grant select on table public.athar_schema_versions to service_role;
