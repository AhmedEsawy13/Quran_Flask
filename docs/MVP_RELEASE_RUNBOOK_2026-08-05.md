# Athar MVP release runbook

Release date: 2026-08-05

## Released state

- Commit: `49cdf09ae698a738c50dbab9965e8236d9ee13b8`
- Public origin: `https://waqfquran-d0b6fce4874e.herokuapp.com`
- GitHub CI run: `31002198379` — passed
- Final deployed smoke test: passed
- Production editor boundary: `/mushaf-editor`, `/classical-review`, and
  `/layout-studio/bahrain` return 404
- Muktafa pilot caches were kept outside the release tree and are not part of
  this public MVP release.

Critical release database fingerprints:

- `data/classical_waqf.db`
  `80ce40c99f87aafecd9ff7ad58c87f987df40d7dd8293119e38e94d322989fc5`
- `data/mushaf-bahrain-layout.db`
  `92b105b13ebf31d257e665161a9c59ab80ec023175f536f1d763ef2d8d6d9ec7`
- `data/tafseer_local.db`
  `59d413cbf6a976414a9a154935488cc2c340b0664065efb07d89be28a115b293`

## Public-dyno configuration

- Keep `ENABLE_EDITOR` unset.
- Keep `EDITOR_DEPLOYMENT` unset.
- Keep `FEATURES` unset unless intentionally selecting the documented public
  modules (`core`, `reading`, `memorize`, and `breathing`).
- If Supabase is used for published data, keep `SUPABASE_URL` and
  `SUPABASE_SERVICE_ROLE_KEY` server-only.
- `EDITOR_SESSION_SECRET` and `EDITOR_DEPLOYMENT=1` belong only on an
  explicitly editor-capable dyno.

## Rollback

For an immediate Heroku release rollback, list releases and roll back to the
last known-good version:

```bash
heroku releases --app YOUR_HEROKU_APP
heroku rollback vN --app YOUR_HEROKU_APP
```

For a source-controlled rollback through the normal deployment path:

```bash
git revert 49cdf09
git push origin main
```

The release commit keeps application code and tracked layout/database changes
together so either rollback path restores a consistent release state.

## Post-launch monitoring

- Check `/api/health` and the public smoke suite after each deploy.
- Confirm editor routes remain 404 on the public origin.
- Watch Heroku application logs for 5xx responses, database-open failures,
  audio proxy failures, and slow tafsir/waqf requests.
- Do not advertise Muktafa as human-reviewed while its 167-row queue remains.
- Keep Manar behind its existing review policy and do not publish new
  classical books during this MVP window.
