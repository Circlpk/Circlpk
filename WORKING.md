# Circlpk — How It Works

A working document for the Circlpk website: what each part does, how the
frontend and backend talk to each other, and how to run and verify it.

Stack: **Flask 3.1.3** + Jinja2 + vanilla JavaScript + SQLite. No build step,
no bundler, no frontend framework. One dependency: Flask.

---

## 1. Running it

```bash
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>. The database is created on first run and the
consultancy chat works with no API key.

Run the checks:

```bash
python test_app.py
```

### Environment variables (all optional)

| Variable | Effect |
| --- | --- |
| `CIRCLPK_ADMIN_PASSWORD` | Turns on `/admin/bookings`. Unset means both admin URLs return 404. |
| `ANTHROPIC_API_KEY` | Switches the chat from the rule-based bot to Claude. |
| `CIRCLPK_DB` | Path to the SQLite file. Defaults to `circlpk.db` beside `app.py`. |

---

## 2. File map

| Path | Role |
| --- | --- |
| `app.py` | Everything server-side: routes, both APIs, admin pages, DB layer, pricing data, chat knowledge base |
| `templates/base.html` | Shared shell — header, nav, footer. Every page extends it. |
| `templates/index / services / about / consultancy / checkout / admin` | The six pages |
| `templates/partials/` | `ring_mark.html` (brand mark), `flag.html` (Pakistan flag) |
| `static/css/style.css` | Design tokens, header, footer, buttons, shared rhythm |
| `static/css/pages.css` | Per-page styling — hero orbit, tier cards, chat panel, checkout, admin cards |
| `static/js/main.js` | Nav dropdown + mobile menu |
| `static/js/checkout.js` | Booking form submit |
| `static/js/consultancy.js` | Chat |
| `static/img/` | Logo and founder photo |
| `test_app.py` | 10 end-to-end checks |
| `requirements.txt` | Dependencies — Flask, plus `anthropic` if you want the chat on Claude |
| `.gitignore` | Keeps `circlpk.db` and `.env` out of version control |

---

## 3. How the frontend and backend connect

Three mechanisms. Most of the site uses the first one and never calls an API.

### 3.1 Server-side rendering (no API call)

Flask puts the data into the HTML before it reaches the browser.

```text
GET /checkout/t2
  → checkout("t2")                                    app.py
  → render_template("checkout.html", tier=TIERS["t2"])
  → {{ '{:,}'.format(tier.price) }}                   checkout.html
  → "Rs 40,000" in the delivered HTML
```

`TIERS` in `app.py` is the single source of truth for all pricing. Changing a
number there updates the services page, the checkout page, the order summary
and the chat's pricing answers together — there is no second copy anywhere.

### 3.2 `url_for()` — routes and links stay in sync

Templates never hardcode a URL. `{{ url_for('checkout', tier='t1') }}` takes
the Python **function name** and produces `/checkout/t1`. Rename a route and
every link follows automatically.

### 3.3 `fetch()` → JSON API

Only two things are dynamic: submitting a booking, and the chat.

#### Booking flow

| Step | Where | What happens |
| --- | --- | --- |
| 1 | `checkout.html` | `<form id="checkoutForm">` |
| 2 | `checkout.js` | `e.preventDefault()` stops the normal browser POST |
| 3 | `checkout.js` | `Object.fromEntries(new FormData(form))` → JS object |
| 4 | `checkout.js` | `fetch('/api/checkout', {method:'POST', body: JSON.stringify(data)})` |
| 5 | `app.py` | Route matches, `request.get_json(silent=True)` |
| 6 | `app.py` | Validate → honeypot check → `insert_booking()` |
| 7 | `app.py` | `jsonify({ok, reference, tier_label})` |
| 8 | `checkout.js` | Reads `result.ok`, renders the confirmation with the reference |

#### Chat flow

`consultancy.js` posts `{message, history}` → `app.py` calls `get_ai_reply()`
→ returns `{reply}` → JS appends it as a bot bubble and pushes it onto
`history` for the next turn.

---

## 4. The contract: the `name` attribute

This is the single most important thing to understand about the integration.
Nothing generates or validates the link between layers — it holds because the
same string is used at every step:

```text
HTML     <input name="company_name">        ← the contract starts here
JS       FormData → data["company_name"]    ← automatic, no mapping code
Python   data.get("company_name")           ← app.py
Python   REQUIRED_FIELDS = ["company_name", ...]
SQLite   company_name TEXT
```

If you rename the field in HTML and nowhere else, the JavaScript keeps working
and the backend **silently stores an empty value** — no error. That is why
`REQUIRED_FIELDS` exists: it makes the server reject a payload whose keys don't
match, instead of writing blanks.

`BOOKING_COLUMNS` in `app.py` plays the same role on the database side. The
INSERT statement, the admin page and the CSV export are all built from that one
tuple, so they cannot drift apart.

---

## 5. Routes

### Pages

| Route | Template | Notes |
| --- | --- | --- |
| `GET /` | `index.html` | Hero with the CSS orbit animation |
| `GET /services` | `services.html` | Three tier cards, prices from `TIERS` |
| `GET /about` | `about.html` | Vision, values, story, founder |
| `GET /consultancy` | `consultancy.html` | Chat panel + prompt chips |
| `GET /checkout/<tier>` | `checkout.html` | `t1`/`t2`/`t3`, case-insensitive; anything else → 404 |

### APIs

**`POST /api/checkout`**

Request:

```json
{
  "company_name": "Northline Traders",
  "contact_name": "Ayesha Khan",
  "contact_role": "Founder",
  "email": "ayesha@northline.pk",
  "phone": "0300 1234567",
  "source": "linkedin",
  "tier": "t2",
  "company_size": "2-10",
  "notes": "Cold emails get opened but nobody books a call."
}
```

Success `200`:

```json
{ "ok": true, "reference": "CPK-260806-3491", "tier_label": "T2: Build the core product" }
```

Errors `400`:

```json
{ "ok": false, "error": "Missing required field(s): company_name, email" }
{ "ok": false, "error": "Unknown tier." }
```

**`POST /api/consultancy`**

Request: `{"message": "What is an ICP?", "history": [{"role": "user", "text": "..."}]}`
Response: `{"reply": "An ICP, ideal customer profile, is ..."}`

Only the last 8 turns of `history` are sent to Claude. An empty message returns
a prompt rather than a blank bubble.

### Admin

| Route | Notes |
| --- | --- |
| `GET /admin/bookings` | All bookings, newest first, one card each |
| `GET /admin/bookings.csv` | Same data as CSV download |

Both use HTTP Basic auth — the browser shows a login box. The username is
ignored; only the password is compared, using `hmac.compare_digest`.

**With `CIRCLPK_ADMIN_PASSWORD` unset, both routes return 404.** The admin area
doesn't exist rather than existing-but-locked, so there is nothing to find or
guess a password against.

---

## 6. Database

SQLite file, one `bookings` table, created automatically on first run.

```sql
CREATE TABLE IF NOT EXISTS bookings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    reference     TEXT UNIQUE,
    created_at    TEXT,
    tier          TEXT,
    company_name  TEXT,
    contact_name  TEXT,
    contact_role  TEXT,
    email         TEXT,
    phone         TEXT,
    source        TEXT,
    company_size  TEXT,
    notes         TEXT
)
```

Connection lifecycle: `get_db()` opens one connection per request and stores it
on Flask's `g`; `@app.teardown_appcontext` closes it when the request ends.

**Booking references.** `CPK-<yymmdd>-<4 digits>`, e.g. `CPK-260806-3491`. The
number is random and the column is `UNIQUE`, so two bookings on the same day can
collide. `insert_booking()` catches `sqlite3.IntegrityError` and draws a new
reference, up to 5 times, instead of returning a 500 and losing the lead.

Query it directly if you prefer:

```bash
sqlite3 circlpk.db "select reference, company_name, tier, email from bookings;"
```

---

## 7. The consultancy chat

Two modes, chosen at request time in `get_ai_reply()`:

**Rule-based (default, no API key).** `KB` is a list of `(regex, answer)` pairs,
checked in order — first match wins. It covers ICPs, prospect vs lead lists,
objection handling, tier comparisons, individual tiers, pricing, cold outreach,
pipelines, and greetings. No match falls through to one of three `FALLBACK_REPLIES`.

Order matters: the T1-vs-T2 comparison pattern must stay **above** the
single-tier `\bt1\b` pattern, or a question naming both tiers gets answered as
if it only named the first one.

**Claude.** If `ANTHROPIC_API_KEY` is set, the call goes to the API with
`SYSTEM_PROMPT` and the last 8 turns. Any exception is logged as a warning and
the rule-based answer is used instead — so a bad key degrades gracefully but
doesn't do so silently.

---

## 8. Security measures in place

| Measure | Where |
| --- | --- |
| Parameterised SQL on every query | `app.py` — no string interpolation of user input |
| Server-side validation | `REQUIRED_FIELDS`, tier whitelist — the browser is never trusted |
| XSS prevention | `checkout.js` escapes via `textContent`; `consultancy.js` uses `textContent` for all messages |
| Honeypot | Off-screen `website` field. Filled = bot → dropped, but the response still looks like success so the bot doesn't retry |
| Constant-time password compare | `hmac.compare_digest` in `require_admin()` |
| Admin hidden by default | No password configured → 404, not 401 |
| Secrets out of the repo | `.gitignore` excludes `*.db` and `.env` |

CSRF is not a concern here: there is no session or cookie authentication, and
the JSON content type triggers a CORS preflight that blocks cross-origin posts.
The admin routes are GET-only and read-only.

---

## 9. Tests

`python test_app.py` — plain `assert` statements, no pytest required, using a
throwaway SQLite file so the real database is untouched.

| Check | What it proves |
| --- | --- |
| `test_every_page_renders` | All 5 pages + all 3 checkout tiers return 200; unknown tier 404s |
| `test_checkout_rejects_a_blank_required_field` | Every required field is actually enforced server-side |
| `test_checkout_rejects_an_unknown_tier` | Tier whitelist works |
| `test_checkout_saves_the_booking_and_returns_a_reference` | Full round trip, verified in the database |
| `test_honeypot_looks_successful_but_stores_nothing` | Bot sees `ok: true`, row count unchanged |
| `test_a_colliding_reference_never_overwrites_a_booking` | Forced collisions never produce a duplicate |
| `test_chat_answers_without_an_api_key` | Rule-based mode works; blank message still replies |
| `test_every_prompt_chip_gets_the_right_answer` | All 5 on-page prompt chips get the correct KB entry |
| `test_admin_needs_the_password` | 401 without / with wrong password, 200 with correct, CSV headers correct |
| `test_admin_does_not_exist_without_a_configured_password` | 404 when no password is set |

Last run:

```text
10 checks passed.
```

Set `CIRCLPK_MODULE=circlpk_single` to run the same suite against the
single-file build.

---

## 10. Verified behaviour

Run against a live server, not just the test client:

```text
/                200      /checkout/t1     200
/services        200      /checkout/t2     200
/about           200      /checkout/t3     200
/consultancy     200      /checkout/t9     404

REAL BOOKING    ok=True  ref=CPK-260806-3491  T2: Build the core product
HONEYPOT BOT    ok=True  (bot sees success)  → not stored
MISSING FIELDS  400  Missing required field(s): company_name, contact_name, ...
BAD TIER        400  Unknown tier.
ADMIN no pass   401       ADMIN wrong pass  401       ADMIN correct  200
CSV             200  reference,created_at,tier,company_name,...
CHAT            5/5 prompt chips answered correctly
```

Server log during the run:

```text
INFO in app: New booking CPK-260806-3491 (t2) from ayesha@northline.pk
INFO in app: Dropped honeypot submission from 127.0.0.1
```

---

## 11. What was fixed

| # | Problem | Fix |
| --- | --- | --- |
| 1 | Mobile nav visible on desktop. `.mobile-nav { display: none }` only existed inside the 860px media query, so above that width the drawer rendered inside the fixed header and spilled across every page. | Base rule added in `style.css` |
| 2 | `"difference between your T1 and T2"` — a prompt chip on the site's own page — returned the T1 answer. The regex was `difference between t1 and t2`; the word `your` broke the match. | Regex now `\bt1\b.{0,40}\bt2\b`; test added |
| 3 | Booking reference collision → unhandled `IntegrityError` → 500 → lost lead | Retry loop, wider random range |
| 4 | `tier` and `stage` held the same value in two columns; the hidden `tier` input and `CHECKOUT_TIER` constant were dead | One field, one column |
| 5 | No spam protection on the public POST endpoint | Honeypot field |
| 6 | Claude failures swallowed by `except Exception: pass` | Logged as a warning |
| 7 | No way to see bookings without a SQLite client | `/admin/bookings` + CSV export |
| 8 | Admin table unusable on phones | Card layout with `auto-fit` grid |
| 9 | Chat allowed concurrent requests; rapid clicks interleaved replies | `waiting` flag |
| 10 | `datetime.utcnow()` deprecated in Python 3.12+ | `datetime.now(timezone.utc)` |
| 11 | Model ID a generation behind | `claude-opus-5` |
| 12 | Dead nav-highlight JS duplicating Jinja logic | Deleted |
| 13 | No `.gitignore` — `circlpk.db` holds real client contact details | Added, `*.db` first |
| 14 | Chat history used `role: 'bot'`, backend expected `'assistant'` (worked only via a fallback branch) | Both sides now say `assistant` |

---

## 12. Still open

### Matters now

- **Bookings are pull, not push.** The admin page has to be opened manually;
  nothing notifies anyone when a lead arrives. Roughly 10 lines of `smtplib`
  once SMTP credentials are available, following the same optional-env-var
  pattern as `ANTHROPIC_API_KEY`.

### Matters when deploying

- **HTTPS is required.** HTTP Basic auth sends the password base64-encoded, not
  encrypted. Fine on localhost, exposed on a public HTTP host.
- **`app.run(debug=True)` is not a production server.** Needs gunicorn or
  waitress. Debug mode on a public host allows arbitrary code execution.
- **No rate limiting.** The honeypot stops simple bots, not a determined script.

---

## 13. Design notes

- Colours are taken from the logo: cream `#FFFCEE`, terracotta `#CD5C5C`.
- Fonts: Fraunces (display), Inter (body), IBM Plex Mono (labels, prices, tier
  codes), loaded from Google Fonts.
- The hero orbit animation is pure CSS — no animation library — and respects
  `prefers-reduced-motion`.
- Breakpoints: 980px, 900px, 860px (nav switches to the mobile drawer), 720px,
  560px. The admin cards use `repeat(auto-fit, minmax(160px, 1fr))` and need no
  breakpoint of their own.
