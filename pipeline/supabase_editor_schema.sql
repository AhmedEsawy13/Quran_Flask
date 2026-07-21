-- Athar mushaf-editor cloud schema (Supabase / Postgres)
-- Run in the Supabase SQL editor once per project.
-- Flask uses the service_role key; anon/authenticated have no access.

create extension if not exists pgcrypto;

-- Per-person invite codes (store hash only; plaintext shown once at creation).
create table if not exists editor_invites (
  id uuid primary key default gen_random_uuid(),
  code_hash text not null unique,
  display_name text not null,
  role text not null default 'editor'
    check (role in ('editor', 'admin')),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  last_used_at timestamptz
);

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
  page_number integer not null check (page_number between 1 and 604),
  reviewed boolean not null default false,
  updated_by uuid references editor_invites(id) on delete set null,
  updated_at timestamptz not null default now(),
  primary key (edition, page_number)
);

-- Append-only audit trail.
create table if not exists editor_audit (
  id bigserial primary key,
  at timestamptz not null default now(),
  actor_id uuid references editor_invites(id) on delete set null,
  actor_name text,
  action text not null
    check (action in ('set_mark', 'clear_mark', 'review_page', 'publish', 'login')),
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

-- Lock down: only service_role (bypasses RLS) may read/write.
alter table editor_invites enable row level security;
alter table editor_marks enable row level security;
alter table editor_progress enable row level security;
alter table editor_audit enable row level security;

-- No policies for anon/authenticated → denied by default under RLS.
-- service_role bypasses RLS in Supabase.
