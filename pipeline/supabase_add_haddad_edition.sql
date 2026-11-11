-- Register «الكويت (الحداد)» (مصحف دولة الكويت بخط محمد سعد الحداد, 1421/2000) as a cloud waqf edition
-- (run once in the Supabase SQL editor). Editable in /mushaf-editor, cloud drafts, publishing and public
-- reading on. Matches core/edition_capabilities.py.
insert into public.editor_edition_capabilities (
  edition, editor_enabled, cloud_draft_enabled,
  publish_enabled, public_read_enabled, updated_at
)
values ('الكويت (الحداد)', true, true, true, true, now())
on conflict (edition) do update
set editor_enabled = excluded.editor_enabled,
    cloud_draft_enabled = excluded.cloud_draft_enabled,
    publish_enabled = excluded.publish_enabled,
    public_read_enabled = excluded.public_read_enabled,
    updated_at = excluded.updated_at;
