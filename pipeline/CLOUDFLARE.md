# Cloudflare (Free) in front of Heroku

Cloudflare cannot proxy `*.herokuapp.com` by itself — you need a **domain you
own**. Then Cloudflare caches `/static/*`, shields the dyno, and terminates TLS.

Live Heroku origin (example): `https://waqfquran-d0b6fce4874e.herokuapp.com`

## 1. Heroku — add the custom domain

```bash
heroku domains:add www.YOURDOMAIN.com -a YOUR_HEROKU_APP
heroku domains:add YOURDOMAIN.com     -a YOUR_HEROKU_APP
heroku domains -a YOUR_HEROKU_APP
```

Copy the **DNS target** Heroku prints (looks like `something.herokudns.com`).

Also set the public URL:

```bash
heroku config:set PUBLIC_BASE_URL=https://www.YOURDOMAIN.com -a YOUR_HEROKU_APP
```

Keep the editor off the public dyno if you can:

```bash
# public web dyno — omit ENABLE_EDITOR
heroku config:unset ENABLE_EDITOR -a YOUR_HEROKU_APP
heroku config:unset EDITOR_DEPLOYMENT -a YOUR_HEROKU_APP
```

## 2. Cloudflare — add the site (Free)

1. [dash.cloudflare.com](https://dash.cloudflare.com) → **Add a domain** → enter `YOURDOMAIN.com`.
2. Choose the **Free** plan.
3. Cloudflare shows two nameservers — set those at your registrar (Namecheap, GoDaddy, …).
4. Wait until the zone status is **Active**.

## 3. DNS records (proxied = orange cloud)

| Type  | Name | Content                         | Proxy |
|-------|------|---------------------------------|-------|
| CNAME | `www` | `something.herokudns.com`      | Proxied |
| CNAME | `@`   | `www` (CNAME flattening) **or** same Heroku DNS target | Proxied |

SSL/TLS mode: **Full (strict)** once Heroku ACM finishes for the custom domain.

## 4. Cache rules (Free)

**Cache static forever** (app already sends `Cache-Control: public, max-age=31536000, immutable` for `/static/`):

- If URI Path starts with `/static` → **Eligible for cache**, Edge TTL = 1 month (or respect origin).

**Never cache the editor:**

- If URI Path starts with `/mushaf-editor` **or** `/api/mushaf-editor` **or** `/layout-studio` **or** `/azhar-layout`  
  → **Bypass cache**.

Optional: under **Speed** → enable Brotli / Early Hints if available.

## 5. Verify

```bash
# Should show cf-ray / server: cloudflare
curl -sI https://www.YOURDOMAIN.com/ | egrep -i 'server|cf-ray|cf-cache'

# After a second hit, static should be HIT
curl -sI 'https://www.YOURDOMAIN.com/static/css/brand.css' | egrep -i 'cf-cache|cache-control'
```

Expect `cf-cache-status: HIT` (or `DYNAMIC` only on HTML).

## Notes

- `atharquran.com` may already be on Cloudflare for a **different** site — do not point it at Heroku unless you intend to replace that site.
- App-side: `ProxyFix` + long static `Cache-Control` are required so Cloudflare and HTTPS behave correctly (see `app.py`).
