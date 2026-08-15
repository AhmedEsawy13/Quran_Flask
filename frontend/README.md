# Athar Next.js frontend

This directory contains Athar's public frontend. Flask remains the source of
truth for Quran data and the tools that have not moved yet.

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

Run the same frontend gate used by GitHub Actions with:

```bash
npm run verify
npm run test:smoke
```

If `python3` resolves to macOS system Python 3.9, point the smoke runner at the
project interpreter, for example `ATHAR_PYTHON=/opt/homebrew/bin/python3 npm run test:smoke`.

## UI foundation

Tailwind CSS v4 provides layout and component utilities through the PostCSS
plugin. Athar's existing `--athar-*` palette, typography, radii, and shadows
are mapped into the Tailwind theme in `app/globals.css`.

Tailwind Preflight and utility styling now cover the shared application chrome,
landing page, and workspace controls. Quran line assembly, edition fonts, glyph
positioning, print rules, and dynamic audio rendering remain explicit CSS where
the renderer benefits from stable semantic selectors.

## Vercel deployment

Create a Vercel project with `frontend` as its Root Directory and configure:

```text
ATHAR_API_ORIGIN=https://<current-heroku-api>
NEXT_PUBLIC_LEGACY_APP_ORIGIN=https://<current-heroku-app>
NEXT_PUBLIC_SITE_URL=https://<next-frontend-domain>
```

The frontend ships the Thmanyah UI/display fonts and the shared Quran fonts.
Mushaf editions load their own Digital Khatt, Old Madina, Amiri, or extracted
page font as needed; the Flask deployment remains the source for backend font
assets during the migration.

## Migration boundary

- `/`, `/read`, `/memorize`, `/waqf`, `/waqf-lab`, `/waqf-practice`, and `/credits` are implemented by Next.js.
- `/backend-api/*` proxies short, cacheable API reads to Flask.
- Internal editor/review surfaces, and voice recording/ASR portions of تدريب and تثبيت, still link to Flask.
- Audio, CV, PDFs, and long-running work must not be proxied through Vercel.
