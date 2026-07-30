# Athar mushaf-editor cloud schema (Supabase / Postgres)
# Cloud drafts + per-person accounts (username + password). Public readers
# only see marks after an **admin** publishes.

## 1. Create project & schema

1. Create a Supabase project.
2. SQL Editor → paste and run [`supabase_editor_schema.sql`](supabase_editor_schema.sql).
3. If you already had the older invite-code schema, also run
   [`supabase_editor_password_auth.sql`](supabase_editor_password_auth.sql).
4. Existing projects should also run
   [`supabase_layout_schema.sql`](supabase_layout_schema.sql) once. It adds the
   Bahrain Layout Studio page/profile tables and is safe to rerun.

## 2. App env vars

```bash
# Editor-capable dyno / laptop
export SUPABASE_URL='https://YOUR_PROJECT.supabase.co'
export SUPABASE_SERVICE_ROLE_KEY='eyJ…'   # Project Settings → API → service_role
export EDITOR_SESSION_SECRET='long-random-string'
export ENABLE_EDITOR=1

# Public read dynos (no editor UI) still need URL + service role so
# /read and مُكْث can load *published* قطر/الكويت/البحرين marks. Omit ENABLE_EDITOR.
# export SUPABASE_URL=…
# export SUPABASE_SERVICE_ROLE_KEY=…
```

Never put `SUPABASE_SERVICE_ROLE_KEY` in the browser or commit it.

## 3. Create accounts

**In the UI (after you have one admin):** open `/mushaf-editor` → **حسابات** →
name + username + role → copy the password once.

**Or CLI** (first admin, before anyone can log in):

```bash
# Admin (you)
python3 pipeline/create_editor_invite.py \
  --name 'Ahmed' --username ahmed --role admin --password 'your-secret'

# Helper
python3 pipeline/create_editor_invite.py \
  --name 'Reviewer 1' --username reviewer1 --role editor
```

Passwords are hashed with Werkzeug (scrypt) before storage. Give people the
plaintext once.

### Migrating older invite-only rows

```bash
python3 pipeline/set_editor_password.py --name 'Mac' --username mac --password '…'
python3 pipeline/set_editor_password.py --name 'Ahmed' --username ahmed --password '…'
```

### If you already ran an older schema

First run [`supabase_atomic_publish.sql`](supabase_atomic_publish.sql) in the
Supabase SQL editor. This installs the transaction used by **اعتماد ونشر**.
Until this migration is installed, publishing intentionally fails instead of
falling back to the old partial-write behavior.

Then run
[`supabase_schema_readiness.sql`](supabase_schema_readiness.sql). It records
the installed editor/layout migration versions without granting browser
access. Verify the project at any time with:

```bash
python3 pipeline/check_supabase_readiness.py
```

### Hand-labeled CV waqf crops (training sync)

For labeling on one machine and training on another, run once in the SQL
editor: [`supabase_cv_waqf_hand.sql`](supabase_cv_waqf_hand.sql). Then:

```bash
python3 -m pipeline.cv_waqf push-hand --slug shamarly   # upload crops + model
python3 -m pipeline.cv_waqf pull-hand --slug shamarly   # download on the other machine
```

Uses the same `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` as the editor.
Private Storage bucket `cv-waqf-hand` + table `cv_waqf_hand_labels`.

Then run this once so invite create/revoke can be audited (it is already part
of the current full schema):

```sql
alter table editor_audit drop constraint if exists editor_audit_action_check;
alter table editor_audit add constraint editor_audit_action_check
  check (action in (
    'set_mark', 'clear_mark', 'review_page', 'publish', 'login',
    'invite_create', 'invite_revoke',
    'layout_save', 'layout_profile', 'layout_undo',
    'mark_review_decision', 'mark_review_note', 'mark_review_page',
    'progress'
  ));
```

Existing projects should also run
[`supabase_editor_audit_actions.sql`](supabase_editor_audit_actions.sql) once
to widen the action check and add actor/action indexes.
## 4. Migrate existing SQLite marks (optional)

```bash
# Into draft (default) — public unchanged until you publish
python3 pipeline/migrate_waqf_to_supabase.py

# Or seed as already public:
python3 pipeline/migrate_waqf_to_supabase.py --as-published
```

## 5. Workflow

1. Helper opens `/mushaf-editor`, enters username + password.
2. Edits write **draft** rows + audit events.
3. You (admin) review the pending drawer and click **اعتماد**. PostgreSQL locks
   the marks table, verifies that the exact reviewed old/new diff is still
   current, and promotes every addition/update/deletion in one transaction.
   If another editor changed a draft meanwhile, nothing is published and the
   drawer refreshes for another review.
4. Browse `/activity` for the cross-tool audit timeline (login required when
   cloud is configured). Layout saves include a `change_summary` (op, page
   range, ayah line count, first/last keys, changed line endpoints). Export
   the loaded slice as JSON/CSV from the page.
5. `/read` and مُكْث then overlay published cloud marks for قطر/الكويت.

Without Supabase env vars, the editor keeps the old local SQLite write path (laptop workflow).

### Bahrain layout workflow

The committed `data/mushaf-bahrain-layout.db` is the baseline. Each Layout
Studio action uploads a complete snapshot of every affected page (including
both pages for a cross-page move), plus project profile and review progress.
The Bahrain waqf editor reads the same synchronized working database.

Seed or verify an existing reviewed layout:

```bash
python3 pipeline/seed_bahrain_layout_supabase.py
python3 pipeline/seed_bahrain_layout_supabase.py --verify-only
```

The seed is idempotent and never exposes the service-role key to the browser.

## 6. Synchronize approved marks back to SQLite

Supabase is the live source for editor-approved Qatar/Kuwait/Bahrain marks, while the
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

## 7. Automated review pull requests

[`propose-published-waqf-sync.yml`](../.github/workflows/propose-published-waqf-sync.yml)
runs daily and can also be started manually. Configure these repository
**Actions secrets** first:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Repository Settings → Actions → General must also grant workflows read/write
access and allow GitHub Actions to create pull requests.
Until both secrets are configured, scheduled runs exit successfully with a
setup note and make no changes.

The job fetches and validates the complete published snapshot, uploads the
immutable plan and Markdown report as a 30-day artifact, applies that exact
plan to a temporary checkout, rebuilds the research caches, and runs the full
test suite. If versioned files changed, it opens or updates
`automation/published-waqf-sync` as a review PR.

The service-role key is available only to the read-only planning step. The job
never writes to Supabase and never pushes to `main`; a human must review and
merge the PR. Validation failures create a failed run and no branch update.

The separate `production-smoke.yml` workflow checks the deployed HTTP surface
and Supabase schema daily. Configure the `PRODUCTION_BASE_URL` repository
variable in addition to the two Supabase secrets.
