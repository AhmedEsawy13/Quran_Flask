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

First run [`supabase_atomic_publish.sql`](supabase_atomic_publish.sql) in the
Supabase SQL editor. This installs the transaction used by **اعتماد ونشر**.
Until this migration is installed, publishing intentionally fails instead of
falling back to the old partial-write behavior.

Then run this once so invite create/revoke can be audited (it is already part
of the current full schema):

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
3. You (admin) review the pending drawer and click **اعتماد**. PostgreSQL locks
   the marks table, verifies that the exact reviewed old/new diff is still
   current, and promotes every addition/update/deletion in one transaction.
   If another editor changed a draft meanwhile, nothing is published and the
   drawer refreshes for another review.
4. `/read` and مُكْث then overlay published cloud marks for قطر/الكويت.

Without Supabase env vars, the editor keeps the old local SQLite write path (laptop workflow).

## 6. Synchronize approved marks back to SQLite

Supabase is the live source for editor-approved Qatar/Kuwait marks, while the
versioned `data/mushaf_waqf.db` remains the reproducible source used by offline
research and fallback deployments. Synchronization is deliberately two-step.

First, fetch and validate the complete published snapshot. This only writes an
ignored JSON plan and a reviewer-readable Markdown report. The CLI loads the
ignored project `.env` automatically when `python-dotenv` is installed:

```bash
python3 pipeline/sync_published_waqf.py
```

The report lists every addition, update, and deletion. Planning is blocked if
a word does not match the canonical Quran token, a symbol is invalid, or the
cloud snapshot has less than 80% of the local mark count (usually evidence of
an incomplete initial migration).

After reviewing `review.md`, apply that exact plan:

```bash
python3 pipeline/sync_published_waqf.py --apply \
  artifacts/published-waqf-sync/YYYYMMDDTHHMMSSZ/plan.json
```

Apply aborts if either the plan or SQLite database changed after review. It
creates an ignored database backup, updates all marks in one transaction,
checks SQLite integrity, and regenerates `data/research_cache/*.json`.

For offline inspection or CI, pass `--source-json published-rows.json`. Use
`--edition قطر` or `--edition الكويت` to review one edition. `--skip-research`
is intended only for tests or an explicitly staged cache rebuild.
