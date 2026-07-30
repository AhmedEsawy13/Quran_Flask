-- Hand-labeled waqf glyph crops for CV training (multi-machine sync).
-- Run once in Supabase SQL Editor, then:
--   python3 -m pipeline.cv_waqf push-hand
--   python3 -m pipeline.cv_waqf pull-hand

create table if not exists public.cv_waqf_hand_labels (
  id text primary key,
  edition text not null,
  slug text not null,
  page integer not null,
  symbol text not null,
  box jsonb not null,
  crop_path text not null,
  created_at timestamptz,
  updated_at timestamptz not null default now()
);

create index if not exists cv_waqf_hand_labels_slug_page_idx
  on public.cv_waqf_hand_labels (slug, page);

create index if not exists cv_waqf_hand_labels_symbol_idx
  on public.cv_waqf_hand_labels (symbol);

alter table public.cv_waqf_hand_labels enable row level security;

-- Service role bypasses RLS; no browser policies on purpose (offline training data).

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'cv-waqf-hand',
  'cv-waqf-hand',
  false,
  5242880,
  array['image/png', 'application/json', 'application/octet-stream']
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;
