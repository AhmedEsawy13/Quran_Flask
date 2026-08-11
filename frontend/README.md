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

Tailwind Preflight is intentionally disabled while the legacy component CSS is
migrated incrementally. Quran line assembly, edition fonts, glyph positioning,
print rules, and dynamic audio rendering remain explicit CSS rather than
utility-only styling.

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

- `/`, `/read`, the core `/memorize` session, and the daily-use `/waqf` guide are implemented by Next.js.
- `/backend-api/*` proxies short, cacheable API reads to Flask.
- تدريب, the editor, the مُكْث research lab, and the voice-recitation portion of تثبيت still link to Flask.
- Audio, CV, PDFs, and long-running work must not be proxied through Vercel.
