# Browser smoke matrix

`scripts/browser_smoke_matrix.py` protects the seven critical user journeys:
reader, تثبيت, مكث, Mushaf editor, Layout Studio, mark review, and CV labeling.
Every journey runs in Chromium at desktop (`1366×900`) and mobile (`390×844`)
widths.

The local runner starts the full Flask app, disables Supabase, blocks third-party
network requests, waits for real local data to render, checks the critical page
shell for horizontal clipping, and rejects local HTTP errors, browser exceptions,
console errors, and a visible loading state left behind. It never performs a
write interaction. The CV journey uses a deterministic scan fixture because page
scans are intentionally not committed; its auth, queue, labels, and word-seat
payloads still come from the real local APIs. The local run also hashes the
published waqf database before and after all journeys and fails if a GET path
mutates it.

```bash
python3 scripts/browser_smoke_matrix.py
python3 scripts/browser_smoke_matrix.py --scenario mobile --journey memorize
python3 scripts/browser_smoke_matrix.py --base-url http://127.0.0.1:5001
```

JSON, Markdown, and failure screenshots are written under
`artifacts/browser-smoke/`. GitHub Actions runs the complete 14-case matrix and
uploads those artifacts when a case fails.
