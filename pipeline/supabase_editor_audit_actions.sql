-- Widen editor_audit.action for activity log coverage.
-- Run once in the Supabase SQL editor (safe to re-run).

create table if not exists public.athar_schema_versions (
  component text primary key,
  version integer not null check (version > 0),
  updated_at timestamptz not null default now()
);

alter table public.editor_audit drop constraint if exists editor_audit_action_check;

alter table public.editor_audit add constraint editor_audit_action_check
  check (action in (
    'set_mark',
    'clear_mark',
    'review_page',
    'publish',
    'login',
    'invite_create',
    'invite_revoke',
    'layout_save',
    'layout_profile',
    'layout_undo',
    'mark_review_decision',
    'mark_review_note',
    'mark_review_page',
    'progress'
  ));

create index if not exists editor_audit_actor_at_idx
  on public.editor_audit (actor_id, at desc);

create index if not exists editor_audit_action_at_idx
  on public.editor_audit (action, at desc);

insert into public.athar_schema_versions (component, version, updated_at)
values ('editor', 4, now())
on conflict (component) do update
set version = greatest(athar_schema_versions.version, excluded.version),
    updated_at = excluded.updated_at;

alter table public.athar_schema_versions enable row level security;
revoke all on table public.athar_schema_versions from anon, authenticated;
grant select on table public.athar_schema_versions to service_role;
