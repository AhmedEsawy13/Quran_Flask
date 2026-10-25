-- Register «المساحة» as a cloud waqf edition (run once in the Supabase SQL editor).
-- Cloud drafts, publishing and public reading on (the column covers the whole book since
-- 2026-10-25); not editable in /mushaf-editor. Matches core/edition_capabilities.py.
insert into public.editor_edition_capabilities (
  edition, editor_enabled, cloud_draft_enabled,
  publish_enabled, public_read_enabled, updated_at
)
values ('المساحة', false, true, true, true, now())
on conflict (edition) do update
set editor_enabled = excluded.editor_enabled,
    cloud_draft_enabled = excluded.cloud_draft_enabled,
    publish_enabled = excluded.publish_enabled,
    public_read_enabled = excluded.public_read_enabled,
    updated_at = excluded.updated_at;
