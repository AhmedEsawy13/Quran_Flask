-- Athar mushaf-editor cloud schema (Supabase / Postgres)
-- Run in the Supabase SQL editor once per project.
-- Flask uses the service_role key; anon/authenticated have no access.

create extension if not exists pgcrypto;

create table if not exists public.athar_schema_versions (
  component text primary key,
  version integer not null check (version > 0),
  updated_at timestamptz not null default now()
);

-- Explicit cloud-edition capabilities. Runtime/readiness code validates against
-- this contract instead of inferring support from legacy SQLite columns.
create table if not exists public.editor_edition_capabilities (
  edition text primary key,
  editor_enabled boolean not null default false,
  cloud_draft_enabled boolean not null default false,
  publish_enabled boolean not null default false,
  public_read_enabled boolean not null default false,
  updated_at timestamptz not null default now(),
  check (not publish_enabled or cloud_draft_enabled)
);

insert into public.editor_edition_capabilities (
  edition, editor_enabled, cloud_draft_enabled,
  publish_enabled, public_read_enabled, updated_at
)
values
  ('قطر', true, true, true, true, now()),
  ('الكويت', true, true, true, true, now()),
  ('البحرين', true, true, true, true, now())
on conflict (edition) do update
set editor_enabled = excluded.editor_enabled,
    cloud_draft_enabled = excluded.cloud_draft_enabled,
    publish_enabled = excluded.publish_enabled,
    public_read_enabled = excluded.public_read_enabled,
    updated_at = excluded.updated_at;

-- Editor accounts (username + password). code_hash is legacy/optional.
create table if not exists editor_invites (
  id uuid primary key default gen_random_uuid(),
  code_hash text unique,
  username text,
  password_hash text,
  display_name text not null,
  role text not null default 'editor'
    check (role in ('editor', 'admin')),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  last_used_at timestamptz
);

create unique index if not exists editor_invites_username_lower_idx
  on editor_invites (lower(username))
  where username is not null;

-- Draft + published marks. edition is free text so future mushafs plug in.
-- token_index is 0-based offset within the ayah (matches layout word_id - first_id).
create table if not exists editor_marks (
  id uuid primary key default gen_random_uuid(),
  edition text not null,
  surah integer not null check (surah between 1 and 114),
  ayah integer not null check (ayah >= 1),
  token_index integer not null check (token_index >= 0),
  status text not null check (status in ('draft', 'published')),
  symbol text not null default '',
  word_text text,
  updated_by uuid references editor_invites(id) on delete set null,
  updated_at timestamptz not null default now(),
  unique (edition, surah, ayah, token_index, status)
);

create index if not exists editor_marks_edition_status_idx
  on editor_marks (edition, status);
create index if not exists editor_marks_ayah_idx
  on editor_marks (edition, status, surah, ayah);

-- Reviewed pages in the editor workspace (draft).
create table if not exists editor_progress (
  edition text not null,
  page_number integer not null check (page_number >= 1),
  reviewed boolean not null default false,
  updated_by uuid references editor_invites(id) on delete set null,
  updated_at timestamptz not null default now(),
  primary key (edition, page_number)
);

-- Layout Studio stores complete page snapshots because one editor action can
-- rebalance several lines (and sometimes two neighboring pages). The bundled
-- SQLite database remains the baseline; rows here are durable overrides.
create table if not exists editor_layout_pages (
  edition text not null,
  page_number integer not null check (page_number >= 1),
  lines jsonb not null check (jsonb_typeof(lines) = 'array'),
  updated_by uuid references editor_invites(id) on delete set null,
  updated_at timestamptz not null default now(),
  primary key (edition, page_number)
);

create index if not exists editor_layout_pages_updated_idx
  on editor_layout_pages (edition, updated_at desc);

-- Geometry settings belong to the layout project too, so a reviewer opening
-- the project on another machine gets the same line/header budget.
create table if not exists editor_layout_profiles (
  edition text primary key,
  profile jsonb not null check (jsonb_typeof(profile) = 'object'),
  updated_by uuid references editor_invites(id) on delete set null,
  updated_at timestamptz not null default now()
);

-- Append-only audit trail.
create table if not exists editor_audit (
  id bigserial primary key,
  at timestamptz not null default now(),
  actor_id uuid references editor_invites(id) on delete set null,
  actor_name text,
  action text not null
    check (action in (
      'set_mark', 'clear_mark', 'review_page', 'publish', 'login',
      'invite_create', 'invite_revoke',
      'layout_save', 'layout_profile', 'layout_undo',
      'mark_review_decision', 'mark_review_note', 'mark_review_page',
      'progress'
    )),
  edition text,
  surah integer,
  ayah integer,
  token_index integer,
  word_id integer,
  page_number integer,
  old_symbol text,
  new_symbol text,
  meta jsonb
);

create index if not exists editor_audit_at_idx on editor_audit (at desc);
create index if not exists editor_audit_edition_idx on editor_audit (edition, at desc);
create index if not exists editor_audit_actor_at_idx on editor_audit (actor_id, at desc);
create index if not exists editor_audit_action_at_idx on editor_audit (action, at desc);

-- Publish the exact diff an admin reviewed in one PostgreSQL transaction.
-- The table lock prevents draft writes between snapshot validation and commit.
create or replace function public.publish_editor_edition(
  p_edition text,
  p_actor_id uuid,
  p_actor_name text,
  p_expected_changes jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_changes jsonb;
  v_count integer;
begin
  if not exists (
    select 1
    from public.editor_edition_capabilities c
    where c.edition = p_edition
      and c.publish_enabled
  ) then
    raise exception 'invalid publish edition' using errcode = '22023';
  end if;
  if p_expected_changes is null or jsonb_typeof(p_expected_changes) <> 'array' then
    raise exception 'expected publish snapshot is required' using errcode = '22023';
  end if;

  lock table public.editor_marks in share row exclusive mode;

  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'surah', d.surah,
        'ayah', d.ayah,
        'token_index', d.token_index,
        'old_symbol', coalesce(p.symbol, ''),
        'new_symbol', coalesce(d.symbol, '')
      ) order by d.surah, d.ayah, d.token_index
    ),
    '[]'::jsonb
  )
  into v_changes
  from public.editor_marks d
  left join public.editor_marks p
    on p.edition = d.edition
   and p.surah = d.surah
   and p.ayah = d.ayah
   and p.token_index = d.token_index
   and p.status = 'published'
  where d.edition = p_edition
    and d.status = 'draft'
    and coalesce(d.symbol, '') <> coalesce(p.symbol, '');

  if p_expected_changes <> v_changes then
    raise exception 'publish snapshot changed; refresh pending changes'
      using errcode = '40001';
  end if;

  v_count := jsonb_array_length(v_changes);

  delete from public.editor_marks p
  using public.editor_marks d
  where d.edition = p_edition
    and d.status = 'draft'
    and coalesce(d.symbol, '') = ''
    and p.edition = d.edition
    and p.surah = d.surah
    and p.ayah = d.ayah
    and p.token_index = d.token_index
    and p.status = 'published'
    and coalesce(p.symbol, '') <> '';

  insert into public.editor_marks (
    edition, surah, ayah, token_index, status, symbol,
    word_text, updated_by, updated_at
  )
  select
    d.edition, d.surah, d.ayah, d.token_index, 'published', d.symbol,
    d.word_text, p_actor_id, now()
  from public.editor_marks d
  left join public.editor_marks p
    on p.edition = d.edition
   and p.surah = d.surah
   and p.ayah = d.ayah
   and p.token_index = d.token_index
   and p.status = 'published'
  where d.edition = p_edition
    and d.status = 'draft'
    and coalesce(d.symbol, '') <> ''
    and coalesce(d.symbol, '') <> coalesce(p.symbol, '')
  on conflict (edition, surah, ayah, token_index, status)
  do update set
    symbol = excluded.symbol,
    word_text = excluded.word_text,
    updated_by = excluded.updated_by,
    updated_at = excluded.updated_at;

  insert into public.editor_audit (
    actor_id, actor_name, action, edition, meta
  ) values (
    p_actor_id, p_actor_name, 'publish', p_edition,
    jsonb_build_object('count', v_count, 'changes', v_changes)
  );

  return jsonb_build_object(
    'edition', p_edition,
    'published', v_count,
    'changes', v_changes
  );
end;
$$;

revoke all on function public.publish_editor_edition(text, uuid, text, jsonb)
  from public;
grant execute on function public.publish_editor_edition(text, uuid, text, jsonb)
  to service_role;

-- Lock down: only service_role (bypasses RLS) may read/write.
alter table editor_invites enable row level security;
alter table public.editor_edition_capabilities enable row level security;
alter table editor_marks enable row level security;
alter table editor_progress enable row level security;
alter table editor_layout_pages enable row level security;
alter table editor_layout_profiles enable row level security;
alter table editor_audit enable row level security;

-- No policies for anon/authenticated → denied by default under RLS.
-- service_role bypasses RLS in Supabase.
revoke all on table public.editor_edition_capabilities
  from public, anon, authenticated;
grant select on table public.editor_edition_capabilities to service_role;

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
