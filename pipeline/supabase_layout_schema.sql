-- Durable Layout Studio overrides.
-- Safe to run more than once in the Supabase SQL editor.

create table if not exists public.editor_layout_pages (
  edition text not null,
  page_number integer not null check (page_number >= 1),
  lines jsonb not null check (jsonb_typeof(lines) = 'array'),
  updated_by uuid references public.editor_invites(id) on delete set null,
  updated_at timestamptz not null default now(),
  primary key (edition, page_number)
);

create index if not exists editor_layout_pages_updated_idx
  on public.editor_layout_pages (edition, updated_at desc);

create table if not exists public.editor_layout_profiles (
  edition text primary key,
  profile jsonb not null check (jsonb_typeof(profile) = 'object'),
  updated_by uuid references public.editor_invites(id) on delete set null,
  updated_at timestamptz not null default now()
);

alter table public.editor_layout_pages enable row level security;
alter table public.editor_layout_profiles enable row level security;

-- No anon/authenticated policies: Flask writes with service_role only.
