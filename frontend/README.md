# Athar Next.js frontend pilot

This directory is an isolated frontend migration pilot. Flask remains the
source of truth for Quran data and all existing tools.

Production frontend: <https://athar-web-teal.vercel.app>

Production API and legacy tools:
<https://waqfquran-d0b6fce4874e.herokuapp.com>

## Local development

Run Flask on port `5001`, then:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. Short browser reads under `/backend-api/*` are
rewritten to `${ATHAR_API_ORIGIN}/api/*`, keeping the browser same-origin while
the migration is in progress.

## Vercel pilot

Create a Vercel project with `frontend` as its Root Directory and configure:

```text
ATHAR_API_ORIGIN=https://<current-heroku-api>
NEXT_PUBLIC_LEGACY_APP_ORIGIN=https://<current-heroku-app>
NEXT_PUBLIC_SITE_URL=https://<next-frontend-domain>
```

The pilot intentionally ships only three fonts: the UI medium, display black,
and the default Uthmanic Hafs font. Page-specific Mushaf fonts stay on the
Python deployment until their renderer is migrated.

## Migration boundary

- `/` and `/read` are implemented by Next.js.
- `/backend-api/*` proxies short, cacheable API reads to Flask.
- مُكْث, تثبيت, تدريب, and the editor still link to Flask.
- Audio, CV, PDFs, and long-running work must not be proxied through Vercel.
