-- Username + password auth for mushaf-editor accounts (editor_invites).
-- Run once in the Supabase SQL editor after the base schema.
-- Existing invite rows keep working only after you set username + password
-- via: python3 pipeline/set_editor_password.py ...

alter table editor_invites
  add column if not exists username text;

alter table editor_invites
  add column if not exists password_hash text;

-- Login is case-insensitive on username.
create unique index if not exists editor_invites_username_lower_idx
  on editor_invites (lower(username))
  where username is not null;

-- New accounts no longer need invite codes; allow null code_hash.
alter table editor_invites
  alter column code_hash drop not null;
