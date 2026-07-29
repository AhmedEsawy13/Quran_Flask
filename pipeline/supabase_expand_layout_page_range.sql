-- Allow Layout Studio editions longer than the 604-page Madinah layout.
-- Safe to run more than once in the Supabase SQL editor.

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
