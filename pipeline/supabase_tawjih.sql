-- Contemporary توجيه (د. أحمد صابر عبدالهادي, @Dr_ahmed21)
-- Documents the live Mushaf_Editor schema (ref tooqdesjgfeicelichgq).
-- NOT a classical waqf book. Do not write these rows into classical_waqf.db.
-- Flask reads with the service_role key; anon/authenticated have no policies.
-- Idempotent: safe to re-run in the Supabase SQL editor.

-- Archive of harvested X posts. kind is the post type as stored by the
-- harvester (منشور / رد / إعادة تغريد / سلسلة / اقتباس).
create table if not exists public.dr_ahmed21_posts (
  tweet_id text primary key,
  seq integer,
  posted_at timestamptz,
  kind text not null
    check (kind in ('منشور', 'رد', 'إعادة تغريد', 'سلسلة', 'اقتباس')),
  post_text text,
  reply_text text,
  reply_to_user text,
  reply_to_url text,
  url text not null,
  replies integer,
  likes integer,
  retweets integer,
  quotes integer,
  views integer,
  bookmarks integer,
  related_waqf boolean,
  hashtags text,
  media text
);

create index if not exists dr_ahmed21_posts_seq_idx
  on public.dr_ahmed21_posts (seq);
create index if not exists dr_ahmed21_posts_kind_idx
  on public.dr_ahmed21_posts (kind);
create index if not exists dr_ahmed21_posts_posted_at_idx
  on public.dr_ahmed21_posts (posted_at);

-- Verse-aligned توجيه. One tweet may yield several spans; skipped posts
-- keep null coordinates. align_conf=1 means a unique exact/prefix QPC match.
-- related_waqf on the source post is NOT a publish filter.
create table if not exists public.tawjih (
  id bigint generated always as identity primary key,
  tweet_id text not null,
  surah integer check (surah is null or surah between 1 and 114),
  ayah integer check (ayah is null or ayah >= 1),
  wpos integer check (wpos is null or wpos >= 0),
  quote text,
  note text not null default '',
  grade text,
  status text not null
    check (status in ('published', 'review', 'skipped')),
  align_conf integer not null default 0
    check (align_conf in (0, 1)),
  skip_reason text,
  locator text
);

-- Span identity for aligned rows. Postgres treats NULLs as distinct, so
-- skipped rows with null coordinates do not collide.
create unique index if not exists tawjih_span_uidx
  on public.tawjih (tweet_id, surah, ayah, wpos);

create index if not exists tawjih_verse_idx
  on public.tawjih (surah, ayah);

create index if not exists tawjih_published_verse_idx
  on public.tawjih (surah, ayah)
  where status = 'published' and align_conf = 1;

create index if not exists tawjih_tweet_idx
  on public.tawjih (tweet_id);

create index if not exists tawjih_status_idx
  on public.tawjih (status);

alter table public.dr_ahmed21_posts enable row level security;
alter table public.tawjih enable row level security;

-- Service role bypasses RLS; no browser/anon policies on purpose.
