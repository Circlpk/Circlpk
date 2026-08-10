"""
Circlpk - Flask backend
=======================

Serves the marketing site (home, services, about, consultancy), two small
JSON APIs, and a password-protected admin view:

  POST /api/checkout      -> stores a booking request in SQLite, returns a
                              booking reference the client can quote back to us.
  POST /api/consultancy   -> powers the "AI mode" on the Consultancy page.
                              Uses a rule-based business-development assistant
                              by default. If an ANTHROPIC_API_KEY environment
                              variable is present, it will use the real Claude
                              API instead for richer answers (see
                              get_ai_reply() below).
  GET  /admin/bookings    -> every booking request, newest first, behind HTTP
  GET  /admin/bookings.csv   basic auth. Both 404 unless CIRCLPK_ADMIN_PASSWORD
                              is set.

Run locally with:
    pip install flask
    python app.py
Then open http://127.0.0.1:5000

Checks: python test_app.py
"""

import os
import re
import csv
import hmac
import random
import smtplib
import sqlite3
import datetime
from email.message import EmailMessage
from io import StringIO
from pathlib import Path

from flask import Flask, render_template, request, jsonify, abort, g, Response

BASE_DIR = Path(__file__).resolve().parent

# Override CIRCLPK_DB to put the database somewhere else (a mounted volume in
# production, a throwaway file in tests).
DB_PATH = Path(os.environ.get("CIRCLPK_DB", BASE_DIR / "circlpk.db"))

# No password set means the /admin pages do not exist at all (they 404).
ADMIN_PASSWORD = os.environ.get("CIRCLPK_ADMIN_PASSWORD", "")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Tier / pricing data (single source of truth, used by services + checkout)
# ---------------------------------------------------------------------------

TIERS = {
    "t1": {
        "key": "t1",
        "label": "T1",
        "name": "Audit",
        "short": "the audit",
        "price": 18000,
        "cadence": "One time payment",
        "desc": "A full audit of your current outbound, where the targeting is off, "
                "and the exact point where deals keep dying.",
    },
    "t2": {
        "key": "t2",
        "label": "T2",
        "name": "Build the core product",
        "short": "T2 build",
        "price": 40000,
        "cadence": "One time payment",
        "desc": "Discovery call, then the full BD playbook: ICP, prospect list, "
                "cold outreach sequence, objection handling doc and pipeline tracker.",
    },
    "t3": {
        "key": "t3",
        "label": "T3",
        "name": "Build and run",
        "short": "T3 build and run",
        "price": 50000,
        "cadence": "Per month, for the contract term",
        "desc": "We operate the system with your team for an agreed stretch of time, "
                "so the pipeline keeps moving after handover.",
    },
}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Written by the checkout API, read back by the admin page and the CSV export.
# Keeping the order in one place means the three never drift apart.
BOOKING_COLUMNS = (
    "reference",
    "created_at",
    "tier",
    "company_name",
    "contact_name",
    "contact_role",
    "email",
    "phone",
    "source",
    "company_size",
    "notes",
)


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT UNIQUE,
                created_at TEXT,
                tier TEXT,
                company_name TEXT,
                contact_name TEXT,
                contact_role TEXT,
                email TEXT,
                phone TEXT,
                source TEXT,
                company_size TEXT,
                notes TEXT
            )
            """
        )
        db.commit()


def make_reference():
    return "CPK-" + datetime.datetime.now().strftime("%y%m%d") + "-" + str(random.randint(1000, 9999))


# ---------------------------------------------------------------------------
# Booking email notification
# ---------------------------------------------------------------------------
#
# Optional, same pattern as ANTHROPIC_API_KEY: unset -> silently skipped.
# Set these on the host (never commit them to a file):
#   CIRCLPK_SMTP_HOST      e.g. smtp.gmail.com / smtp-mail.outlook.com
#   CIRCLPK_SMTP_PORT      e.g. 587 (default if unset)
#   CIRCLPK_SMTP_USER      the business email address that sends the mail
#   CIRCLPK_SMTP_PASSWORD  an app password for that email account (not the
#                          normal login password — see the deploy guide)
#   CIRCLPK_NOTIFY_EMAIL   where the notification should land (defaults to
#                          CIRCLPK_SMTP_USER if unset)

def send_booking_email(reference, tier_label, values_by_column):
    host = os.environ.get("CIRCLPK_SMTP_HOST")
    user = os.environ.get("CIRCLPK_SMTP_USER")
    password = os.environ.get("CIRCLPK_SMTP_PASSWORD")
    if not (host and user and password):
        return  # email notifications not configured — skip quietly

    port = int(os.environ.get("CIRCLPK_SMTP_PORT", "587"))
    to_addr = os.environ.get("CIRCLPK_NOTIFY_EMAIL", user)

    body_lines = [f"New Circlpk booking — {reference}", f"Tier: {tier_label}", ""]
    for col in BOOKING_COLUMNS:
        if col in ("reference", "created_at"):
            continue
        body_lines.append(f"{col.replace('_', ' ').title()}: {values_by_column.get(col, '')}")

    msg = EmailMessage()
    msg["Subject"] = f"New booking: {reference}"
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content("\n".join(body_lines))

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
    except Exception:
        app.logger.warning("Booking email notification failed", exc_info=True)


def insert_booking(values):
    """
    Store a booking and return its reference.

    `reference` is random and the column is UNIQUE, so two bookings on the same
    day can collide. Draw again instead of handing the client a 500 and losing
    the lead.
    """
    columns = ", ".join(BOOKING_COLUMNS)
    placeholders = ", ".join("?" * len(BOOKING_COLUMNS))
    db = get_db()

    for _ in range(5):
        reference = make_reference()
        try:
            db.execute(
                f"INSERT INTO bookings ({columns}) VALUES ({placeholders})",
                (reference, *values),
            )
            db.commit()
            return reference
        except sqlite3.IntegrityError:
            continue

    raise RuntimeError("Could not allocate a unique booking reference after 5 attempts.")


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.context_processor
def inject_globals():
    return {"current_year": datetime.datetime.now().year}


@app.route("/")
def index():
    return render_template("index.html", active_page="home")


@app.route("/services")
def services():
    return render_template("services.html", active_page="services")


@app.route("/about")
def about():
    return render_template("about.html", active_page="about")


@app.route("/consultancy")
def consultancy():
    return render_template("consultancy.html", active_page="consultancy")


@app.route("/checkout/<tier>")
def checkout(tier):
    tier = tier.lower()
    if tier not in TIERS:
        abort(404)
    return render_template(
        "checkout.html",
        active_page="services",
        tier=TIERS[tier],
        all_tiers=TIERS,
    )


# ---------------------------------------------------------------------------
# API: checkout
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = ["company_name", "contact_name", "contact_role", "email", "phone", "source", "tier"]


@app.route("/api/checkout", methods=["POST"])
def api_checkout():
    data = request.get_json(silent=True) or {}

    missing = [f for f in REQUIRED_FIELDS if not str(data.get(f, "")).strip()]
    if missing:
        return jsonify({"ok": False, "error": f"Missing required field(s): {', '.join(missing)}"}), 400

    tier_key = str(data.get("tier", "")).strip().lower()
    if tier_key not in TIERS:
        return jsonify({"ok": False, "error": "Unknown tier."}), 400

    tier = TIERS[tier_key]
    tier_label = f"{tier['label']}: {tier['name']}"

    # Honeypot: the "website" field is positioned off-screen, so a human never
    # fills it. Answer like a success so the bot doesn't retry with it cleared.
    if str(data.get("website", "")).strip():
        app.logger.info("Dropped honeypot submission from %s", request.remote_addr)
        return jsonify({"ok": True, "reference": make_reference(), "tier_label": tier_label})

    def field(name):
        return str(data.get(name, "")).strip()

    booking_values = {
        "tier": tier_key,
        "company_name": field("company_name"),
        "contact_name": field("contact_name"),
        "contact_role": field("contact_role"),
        "email": field("email"),
        "phone": field("phone"),
        "source": field("source"),
        "company_size": field("company_size"),
        "notes": field("notes"),
    }

    reference = insert_booking(
        (
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            tier_key,
            field("company_name"),
            field("contact_name"),
            field("contact_role"),
            field("email"),
            field("phone"),
            field("source"),
            field("company_size"),
            field("notes"),
        )
    )
    app.logger.info("New booking %s (%s) from %s", reference, tier_key, field("email"))
    send_booking_email(reference, tier_label, booking_values)

    return jsonify({"ok": True, "reference": reference, "tier_label": tier_label})


# ---------------------------------------------------------------------------
# Admin: see the bookings without opening a SQLite client
# ---------------------------------------------------------------------------

def require_admin():
    """Returns a 401 response when the caller isn't authenticated, else None."""
    if not ADMIN_PASSWORD:
        abort(404)  # no password configured, so the admin area doesn't exist

    auth = request.authorization
    if not auth or not hmac.compare_digest(auth.password or "", ADMIN_PASSWORD):
        return Response(
            "Authentication required.",
            401,
            {"WWW-Authenticate": 'Basic realm="Circlpk admin"'},
        )
    return None


def all_bookings():
    return get_db().execute("SELECT * FROM bookings ORDER BY id DESC").fetchall()


@app.route("/admin/bookings")
def admin_bookings():
    denied = require_admin()
    if denied:
        return denied
    return render_template("admin.html", bookings=all_bookings(), tiers=TIERS)


@app.route("/admin/bookings.csv")
def admin_bookings_csv():
    denied = require_admin()
    if denied:
        return denied

    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(BOOKING_COLUMNS)
    for booking in all_bookings():
        writer.writerow([booking[column] for column in BOOKING_COLUMNS])

    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=circlpk-bookings.csv"},
    )


# ---------------------------------------------------------------------------
# API: consultancy chat ("AI mode")
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the Circlpk consultant, a friendly, plain-spoken business
development educator for a Pakistan-based BD studio called Circlpk. Explain
business development concepts (ICPs, prospecting, cold outreach, objection
handling, pipelines, audits) clearly and briefly, in a warm and welcoming
tone, without long dashes. Where it's genuinely relevant, connect the
explanation back to Circlpk's three tiers: T1 Audit (Rs 18,000, one time),
T2 Build the core product (Rs 40,000, one time), T3 Build and run
(Rs 50,000 per month for the contract term). Never invent details about
Circlpk beyond this. Keep replies to 2-4 short sentences unless asked for
more detail."""


def get_ai_reply(message, history):
    """
    Tries the real Claude API if ANTHROPIC_API_KEY is set in the environment.
    Falls back to the rule-based assistant otherwise, so the site works
    fully out of the box with no API key required.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic  # pip install anthropic

            client = anthropic.Anthropic(api_key=api_key)
            msgs = []
            for turn in history[-8:]:
                role = "user" if turn.get("role") == "user" else "assistant"
                msgs.append({"role": role, "content": turn.get("text", "")})
            msgs.append({"role": "user", "content": message})

            resp = client.messages.create(
                model="claude-opus-5",
                max_tokens=400,
                system=SYSTEM_PROMPT,
                messages=msgs,
            )
            return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text").strip()
        except Exception as exc:
            # Log it, then fall through. Without this a bad key or a rate limit
            # silently downgrades the page to the rule-based bot forever.
            app.logger.warning("Claude API call failed, using rule-based reply: %s", exc)

    return rule_based_reply(message)


# A small keyword-matched knowledge base. Order matters: first match wins.
KB = [
    (
        re.compile(r"\bicp\b|ideal customer", re.I),
        "An ICP, ideal customer profile, is a clear description of the exact type of company (and person inside it) "
        "that gets the most value from what you sell, and is easiest for you to close. It covers things like industry, "
        "company size, budget, and the problem they're already feeling. Without one, outreach becomes guesswork. "
        "Building the ICP is the first thing we do in T2, before a single prospect list gets built.",
    ),
    (
        re.compile(r"prospect list.*(lead list|difference)|lead list.*prospect", re.I),
        "A lead list is usually just names and contact details, not filtered for fit. A prospect list is built against "
        "your ICP first, so every name on it is someone worth spending outreach time on. That's why we always define "
        "the ICP before we build the list, in T2.",
    ),
    (
        re.compile(r"objection|already have someone|already working with", re.I),
        "Good objection handling starts with acknowledging the objection honestly instead of arguing past it, then "
        "asking one question that surfaces whether the current setup is actually working well for them. \"We already "
        "have someone doing this\" usually isn't a no, it's a chance to ask what results that's producing so far. "
        "We write a full objection handling doc as part of T2, tailored to what your prospects actually say.",
    ),
    (
        # Any question naming both tiers is a comparison ("T1 vs T2", "difference
        # between your T1 and T2", "should we do T1 or T2"). Must stay above the
        # single-tier patterns below, or the \bt1\b rule answers it first.
        re.compile(r"\bt1\b.{0,40}\bt2\b|\bt2\b.{0,40}\bt1\b", re.I),
        "T1 tells you what's broken in your current outbound. T2 actually builds the replacement system, ICP, "
        "prospect list, sequence, objection doc, tracker. Most clients do T1 first so the T2 build is aimed at "
        "the real problem instead of a guess.",
    ),
    (
        re.compile(r"\bt1\b|\baudit\b", re.I),
        f"T1 is the audit: Rs {TIERS['t1']['price']:,}, one time. {TIERS['t1']['desc']} It's usually the right "
        "starting point if you already have some outbound running but don't know why it isn't converting.",
    ),
    (
        re.compile(r"\bt2\b|build the core|playbook|core product", re.I),
        f"T2 is where we build the core product: Rs {TIERS['t2']['price']:,}, one time. {TIERS['t2']['desc']} "
        "Good next step once you know (from an audit or otherwise) that you need a proper system, not just a fix.",
    ),
    (
        re.compile(r"\bt3\b|build and run|run it\b|\boperate\b", re.I),
        f"T3 is build and run: Rs {TIERS['t3']['price']:,} per month, billed for the length of the contract. "
        f"{TIERS['t3']['desc']} It's for teams who'd rather have us operating the pipeline day to day than "
        "managing it themselves.",
    ),
    (
        re.compile(r"price|pricing|cost|how much", re.I),
        f"T1 (Audit) is Rs {TIERS['t1']['price']:,} one time. T2 (Build the core product) is Rs {TIERS['t2']['price']:,} "
        f"one time. T3 (Build and run) is Rs {TIERS['t3']['price']:,} per month for the contract term. You can also "
        "add special instructions at checkout and we'll adjust the quote to fit your situation.",
    ),
    (
        re.compile(r"outreach.*repl(y|ies).*(no|not).*book|reply.*no meeting|opens.*no reply", re.I),
        "Replies with no bookings usually means the message is fine but the ask isn't clear or easy enough to say yes "
        "to. Common fixes: a lighter first ask (a quick question instead of a 30 minute call), a clearer reason "
        "\"why now,\" or simply following up faster while the reply is still warm. This is exactly what we dig into "
        "during a T1 audit.",
    ),
    (
        re.compile(r"cold (email|outreach|call)|outbound", re.I),
        "Cold outreach works best when it's specific to the person you're reaching, not a template blasted to "
        "everyone. A good sequence has a clear first message tied to a real problem they likely have, a couple of "
        "short follow-ups, and a light, low-pressure ask. We build the full sequence in T2.",
    ),
    (
        re.compile(r"pipeline", re.I),
        "A pipeline is just a visible, up-to-date view of every conversation you're having with prospects and what "
        "stage each one is at. Without one, deals quietly go cold because nobody remembers to follow up. We include a "
        "pipeline tracker in T2 so nothing falls through.",
    ),
    (
        re.compile(r"hi|hello|hey|salam|assalam", re.I),
        "Hey! Happy to talk through anything on business development, outbound, ICPs, objection handling, or our "
        "services. What's on your mind?",
    ),
    (
        re.compile(r"thank", re.I),
        "Anytime! If you want a proper look at where your outbound stands, T1 is the natural next step. "
        "Otherwise, ask away.",
    ),
]

FALLBACK_REPLIES = [
    "That's a good question. Business development, in short, is the discipline of finding the right people to "
    "sell to and building a repeatable way to reach them. Could you tell me a bit more about what part you're "
    "stuck on, targeting, messaging, or follow-up?",
    "I want to give you a proper answer rather than a vague one, could you say a little more about your situation? "
    "For example, do you already have outbound running, or are you starting from zero?",
    "Happy to dig into that. If it helps, T1 is built exactly for this kind of question, a full audit that tells "
    "you precisely where your outbound needs work.",
]


def rule_based_reply(message):
    for pattern, answer in KB:
        if pattern.search(message):
            return answer
    return random.choice(FALLBACK_REPLIES)


@app.route("/api/consultancy", methods=["POST"])
def api_consultancy():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()
    history = data.get("history", []) if isinstance(data.get("history"), list) else []

    if not message:
        return jsonify({"reply": "Type a question whenever you're ready, I'm listening."})

    reply = get_ai_reply(message, history)
    return jsonify({"reply": reply})


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
else:
    init_db()
