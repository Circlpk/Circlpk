# Circlpk website

A Flask + HTML/CSS site for Circlpk, a Pakistan-based business development studio.

## What's inside

- `app.py` — Flask backend: page routes, the checkout API (saves bookings to a local
  SQLite file, `circlpk.db`, created automatically on first run), the consultancy
  chat API, and the password-protected admin pages.
- `test_app.py` — `python test_app.py` exercises every route and both APIs.
- `templates/` — Jinja2 templates (home, services, about, consultancy, checkout, admin)
  plus small reusable partials (the flag, the ring mark).
- `static/css/` — `style.css` (site-wide tokens, header, footer, buttons) and
  `pages.css` (hero orbit animation, tier cards, chat panel, checkout layout).
- `static/js/` — nav behaviour, the checkout form submit, and the consultancy chat.
- `static/img/` — your logo and Suwaibah's photo.

## Running it locally

```bash
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000>. Nothing else to configure: the database is
created on first run and the consultancy chat works without an API key.

Run the checks with:

```bash
python test_app.py
```

### Environment variables (all optional)

| Variable | What it does |
| --- | --- |
| `CIRCLPK_ADMIN_PASSWORD` | Turns on `/admin/bookings`. Unset means the page 404s. |
| `ANTHROPIC_API_KEY` | Switches the consultancy chat from the rule-based bot to Claude. |
| `CIRCLPK_DB` | Path to the SQLite file. Defaults to `circlpk.db` next to `app.py`. |

## Seeing your bookings

Set a password and restart:

```bash
export CIRCLPK_ADMIN_PASSWORD=something-long-and-random   # Windows: set CIRCLPK_ADMIN_PASSWORD=...
python app.py
```

Open <http://127.0.0.1:5000/admin/bookings> — the browser asks for a login
(leave the username blank, or type anything; only the password is checked).
Every request is listed newest first, with a **Download as CSV** link for
working the leads in a spreadsheet.

Without `CIRCLPK_ADMIN_PASSWORD` set, both admin URLs return 404 — there is no
admin page to find, so nothing to guess a password against.

## The consultancy "AI mode"

Out of the box, the Consultancy chat runs on a rule-based assistant (see `KB` in
`app.py`) that answers common business development questions (ICPs, prospect lists,
objection handling, pricing, tier differences) and needs no API key at all.

If you'd rather have it answer with the real Claude model for open-ended questions:

1. `pip install anthropic`
2. Set an environment variable: `export ANTHROPIC_API_KEY=your-key-here`
3. Restart the app. `get_ai_reply()` in `app.py` will automatically use the API
   instead of the rule-based fallback, and falls back gracefully if the call fails
   (a warning is logged, so a bad key doesn't silently disable AI mode).

## Checkout bookings

Every submitted booking form lands in `circlpk.db` (a SQLite file, created the first
time the app runs) in a `bookings` table, along with a reference code like
`CPK-260804-7281` that's shown back to the client. Read them on
`/admin/bookings` (above), or query the file directly:

```bash
sqlite3 circlpk.db "select reference, company_name, tier, email from bookings;"
```

The form carries a hidden `website` field that real visitors never see. Anything
that fills it is a bot, so the submission is dropped and the reply still looks
like a success, which stops the bot retrying.

## Editing prices or tier copy

All three tiers (name, price, billing cadence, description) live in one place: the
`TIERS` dictionary near the top of `app.py`. Change a number there and it updates the
services page, the checkout page, and the consultancy chat's pricing answers together.

## Notes

- The colour palette (cream `#FFFCEE` and terracotta `#CD5C5C`) is lifted directly
  from the Circlpk logo.
- Fonts: Fraunces (display), Inter (body), IBM Plex Mono (labels, prices, tier
  codes), loaded from Google Fonts.
- The hero animation is pure CSS (no external animation library), so it loads
  instantly and respects `prefers-reduced-motion`.
