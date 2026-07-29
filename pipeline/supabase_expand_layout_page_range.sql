-- Allow Layout Studio editions longer than the 604-page Madinah layout.
-- Safe to run more than once in the Supabase SQL editor.

create table if not exists public.athar_schema_versions (
  component text primary key,
  version integer not null check (version > 0),
  updated_at timestamptz not null default now()
);

alter table if exists public.editor_progress
  drop constraint if exists editor_progress_page_number_check;
alter table if exists public.editor_progress
  add constraint editor_progress_page_number_check
  check (page_number >= 1);

alter table if exists public.editor_layout_pages
  drop constraint if exists editor_layout_pages_page_number_check;
alter table if exists public.editor_layout_pages
  add constraint editor_layout_pages_page_number_check
  check (page_number >= 1);

insert into public.athar_schema_versions (component, version, updated_at)
values ('layout', 2, now())
on conflict (component) do update
set version = excluded.version,
    updated_at = excluded.updated_at;

alter table public.athar_schema_versions enable row level security;
revoke all on table public.athar_schema_versions from anon, authenticated;
grant select on table public.athar_schema_versions to service_role;
