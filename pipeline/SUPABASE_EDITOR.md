# Supabase mushaf-editor (قطر / الكويت)

Cloud drafts + per-person invite codes. Public readers only see marks after an **admin** publishes.

## 1. Create project & schema

1. Create a Supabase project.
2. SQL Editor → paste and run [`supabase_editor_schema.sql`](supabase_editor_schema.sql).

## 2. App env vars

```bash
# Editor-capable dyno / laptop
export SUPABASE_URL='https://YOUR_PROJECT.supabase.co'
export SUPABASE_SERVICE_ROLE_KEY='eyJ…'   # Project Settings → API → service_role
export EDITOR_SESSION_SECRET='long-random-string'
export ENABLE_EDITOR=1

# Public read dynos (no editor UI) still need URL + service role so
# /read and مُكْث can load *published* قطر/الكويت marks. Omit ENABLE_EDITOR.
# export SUPABASE_URL=…
# export SUPABASE_SERVICE_ROLE_KEY=…
```

Never put `SUPABASE_SERVICE_ROLE_KEY` in the browser or commit it.

## 3. Create invites

**In the UI (after you have one admin):** open `/mushaf-editor` → **دعوات** → name + role → copy the code once.

**Or CLI** (first admin, before anyone can log in):

```bash
# Admin (you)
python3 pipeline/create_editor_invite.py --name 'Ahmed' --role admin --code 'your-secret-admin-code'

# Helper
python3 pipeline/create_editor_invite.py --name 'Reviewer 1' --role editor --code 'helper-code-here'
```

Codes are hashed with SHA-256 + `EDITOR_SESSION_SECRET` before storage. Give people the plaintext once.

### If you already ran an older schema

Run this once in the SQL editor so invite create/revoke can be audited:

```sql
alter table editor_audit drop constraint if exists editor_audit_action_check;
alter table editor_audit add constraint editor_audit_action_check
  check (action in (
    'set_mark', 'clear_mark', 'review_page', 'publish', 'login',
    'invite_create', 'invite_revoke'
  ));
```

## 4. Migrate existing SQLite marks (optional)

```bash
# Into draft (default) — public unchanged until you publish
python3 pipeline/migrate_waqf_to_supabase.py

# Or seed as already public:
python3 pipeline/migrate_waqf_to_supabase.py --as-published
```

## 5. Workflow

1. Helper opens `/mushaf-editor`, enters their code.
2. Edits write **draft** rows + audit events.
3. You (admin) click **اعتماد** → drafts for that edition become **published**.
4. `/read` and مُكْث then overlay published cloud marks for قطر/الكويت.

Without Supabase env vars, the editor keeps the old local SQLite write path (laptop workflow).
