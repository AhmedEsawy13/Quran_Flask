-- Waqf mark-review decisions (Plan A phone checklist).
-- Run in the Supabase SQL editor once. Service role only (same as editor_*).

create table if not exists waqf_mark_review_decisions (
  edition text not null,
  page_number integer not null check (page_number >= 1),
  word_id integer not null check (word_id >= 0),
  decision text not null check (decision in ('ok', 'wrong', 'extra')),
  our_mark text,
  correct_mark text,
  surah integer,
  ayah integer,
  word_text text,
  updated_by uuid references editor_invites(id) on delete set null,
  updated_at timestamptz not null default now(),
  primary key (edition, page_number, word_id)
);

create index if not exists waqf_mark_review_decisions_edition_idx
  on waqf_mark_review_decisions (edition, page_number);

create table if not exists waqf_mark_review_notes (
  id uuid primary key default gen_random_uuid(),
  edition text not null,
  page_number integer not null check (page_number >= 1),
  note text not null,
  updated_by uuid references editor_invites(id) on delete set null,
  updated_at timestamptz not null default now()
);

create index if not exists waqf_mark_review_notes_edition_idx
  on waqf_mark_review_notes (edition, page_number);

alter table waqf_mark_review_decisions enable row level security;
alter table waqf_mark_review_notes enable row level security;
