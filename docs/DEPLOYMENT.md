# Deployment and operations

Athar runs as two deployables from this one repo:

| Piece | Where | What it serves |
|---|---|---|
| **Flask app** (`app.py`) | Heroku (`Procfile`: `gunicorn app:app --workers 1 --threads 4`) | All data APIs (`/api/*`), fonts, audio redirects, the Flask-rendered pages, and — off by default — the editor tools |
| **Next.js frontend** (`frontend/`) | Vercel (project root directory: `frontend`) | The public product UI (`/`, `/read`, `/memorize`, `/waqf`, `/waqf-lab`, `/waqf-practice`, `/credits`); reads Flask through `/backend-api/*` |

The Flask pages remain fully functional on their own; the Next.js UI is the
public front door while the migration continues (see
[`frontend/README.md`](../frontend/README.md)).

## Flask on Heroku

### Build

- Python version comes from [`.python-version`](../.python-version) (`3.12`, a
  major.minor pin so security patches arrive with each build). CI reads the same file.
- `requirements.txt` is fully pinned (except the deliberate `yt-dlp` floor).
- `bin/post_compile` restores the QUL reciter timestamps (~52 MB, not tracked in
  git) at the release pinned in `reciters/.qul_sync_state.json`. If that download
  fails the build still succeeds and تثبيت simply lists fewer reciters — check
  the build log.

### Configuration

Public dyno — set only what is needed:

| Variable | Public dyno | Notes |
|---|---|---|
| `PUBLIC_BASE_URL` | set | Canonical origin for sitemap / canonical / OG URLs, no trailing slash |
| `FEATURES` | unset | Default is `reading,memorize,breathing` (+ `core`, always on). Set to split modules across dynos |
| `ENABLE_EDITOR` | **unset** | The write-capable editor and every internal tool are mounted only when this is truthy |
| `EDITOR_DEPLOYMENT` | **unset** | Even with `ENABLE_EDITOR`, a Heroku dyno (`DYNO` set) only mounts the editor when this is truthy — keeps a stale flag fail-closed |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | only if published waqf is read from Supabase | Server-side only; never expose to a browser |
| `EDITOR_SESSION_SECRET` | **unset** | Belongs to an explicitly editor-capable dyno only (≥ 32 chars) |

An editor-capable dyno (if you run one) additionally needs `ENABLE_EDITOR=1`,
`EDITOR_DEPLOYMENT=1`, the three Supabase variables, and the schema from
[`SUPABASE_EDITOR.md`](SUPABASE_EDITOR.md). Authorization rules:
[`EDITOR_AUTHORIZATION.md`](EDITOR_AUTHORIZATION.md).

The app is read-only at runtime for every public module: it only opens databases
shipped in the slug, so it scales horizontally across dynos. The tracked
`.db` files are never rebuilt at boot (`tests/test_app_boot.py` enforces this).

### Custom domain and CDN

See [`CLOUDFLARE.md`](CLOUDFLARE.md). The app already sends
`Cache-Control: public, max-age=31536000, immutable` on content-hashed
`/static/*`, `no-store` on editor and error responses, and `no-store` on
`/api/health`; `ProxyFix` makes HTTPS and host detection correct behind
Cloudflare/Heroku.

## Next.js on Vercel

Create a Vercel project with **Root Directory = `frontend`** and set:

```text
ATHAR_API_ORIGIN=https://<flask-origin>            # server-side rewrite target for /backend-api/*
NEXT_PUBLIC_LEGACY_APP_ORIGIN=https://<flask-origin> # Flask-only tools (ASR, editor) link here
NEXT_PUBLIC_SITE_URL=https://<public-frontend-domain>
```

Long audio, CV work and PDFs must never be proxied through Vercel — the browser
talks to Flask (or the audio CDNs) directly.

## Go-live checklist

Run before pointing traffic at a new release:

```bash
python3 -m pytest                                   # full suite
python3 pipeline/audit_release_readiness.py         # databases + canonical layout streams
python3 scripts/smoke_test.py --local               # critical routes, public feature set
python3 scripts/smoke_test.py --local --include-editor
cd frontend && npm run verify && npm run test:smoke # lint + typecheck + build + Playwright
```

Then, against the deployed origin:

```bash
python3 scripts/smoke_test.py --base-url https://<flask-origin>
python3 pipeline/check_supabase_readiness.py        # only if Supabase is configured
```

Confirm by hand:

- [ ] `/api/health` returns `200` with `"status": "healthy"` (and `503` if a dataset failed to load).
- [ ] `/mushaf-editor`, `/layout-studio`, `/font-lab`, `/cv-waqf`, `/classical-review`,
      `/waqf-mark-review`, `/activity`, `/quran-integrity-review` all return **404** on the public origin.
- [ ] `/robots.txt`, `/sitemap.xml`, `/llms.txt` show the public origin, not the Heroku hostname.
- [ ] `PUBLIC_BASE_URL` is set; `ENABLE_EDITOR`, `EDITOR_DEPLOYMENT`, `EDITOR_SESSION_SECRET` are not.
- [ ] Heroku build log shows the QUL reciter restore succeeded.

## Automation that keeps production honest

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | push / PR | Release-database audit, classical-book audits, full pytest |
| `frontend-ci.yml` | push / PR | Lint, typecheck, build, Playwright smoke |
| `browser-smoke.yml` | push / PR | Desktop + mobile journeys across the Flask pages |
| `classical-data-audit.yml`, `mushaf-font-audit.yml` | PR (path-filtered) | Strict classical-data gates; real-Chromium mushaf typography audit |
| `production-smoke.yml` | daily | HTTP smoke of the live origin + Supabase schema/capability check (needs the `PRODUCTION_BASE_URL` repository variable) |
| `sync-qul-reciters.yml` | weekly | Opens a PR when new reciter timestamps are released |
| `sync-qvp-upstream.yml`, `propose-published-waqf-sync.yml` | daily | Open PRs for upstream page-engine pins and admin-published waqf marks |

## Rollback

```bash
heroku releases --app <app>
heroku rollback vN --app <app>
```

or revert the offending commit and push. Code and the tracked databases ship in
the same commit, so either path restores a consistent state.

## Monitoring

- Alert on `/api/health` (uncached, so it reflects the current dyno).
- Watch logs for 5xx, database-open failures, audio-proxy failures and slow
  tafsir/waqf requests. Unexpected errors are logged server-side with the
  traceback and returned to clients as a generic JSON body.

Earlier release notes: [`archive/MVP_RELEASE_RUNBOOK_2026-08-05.md`](archive/MVP_RELEASE_RUNBOOK_2026-08-05.md).
