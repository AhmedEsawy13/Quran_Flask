-- Widen editor_audit.action for activity log coverage.
-- Run once in the Supabase SQL editor (safe to re-run).

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
