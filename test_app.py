"""
End-to-end checks for the Circlpk backend.

    python test_app.py

Uses a throwaway SQLite file, so it never touches the real circlpk.db.
"""

import os
import base64
import tempfile
import importlib
from pathlib import Path

# Must be set before importing: both are read at import time.
os.environ["CIRCLPK_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
os.environ["CIRCLPK_ADMIN_PASSWORD"] = "test-password"

# Defaults to the multi-file app. Point it at the single-file build to prove
# the two behave identically:  CIRCLPK_MODULE=circlpk_single python test_app.py
circlpk = importlib.import_module(os.environ.get("CIRCLPK_MODULE", "app"))

# Deliberately NOT setting app.testing = True: the collision check below asserts
# on a 500 response, and TESTING re-raises the exception instead of returning one.
client = circlpk.app.test_client()

VALID = {
    "company_name": "Northline Traders",
    "contact_name": "Ayesha Khan",
    "contact_role": "Founder",
    "email": "ayesha@northline.pk",
    "phone": "0300 1234567",
    "source": "linkedin",
    "tier": "t2",
    "company_size": "2-10",
    "notes": "Outbound is running but nothing converts past the first reply.",
}


def count_bookings():
    with circlpk.app.app_context():
        return circlpk.get_db().execute("SELECT count(*) FROM bookings").fetchone()[0]


def fetch(reference):
    with circlpk.app.app_context():
        return circlpk.get_db().execute(
            "SELECT * FROM bookings WHERE reference = ?", (reference,)
        ).fetchone()


def basic(password):
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_every_page_renders():
    for path in ["/", "/services", "/about", "/consultancy", "/checkout/t1", "/checkout/T3"]:
        assert client.get(path).status_code == 200, path
    assert client.get("/checkout/t9").status_code == 404


def test_checkout_rejects_a_blank_required_field():
    for field in circlpk.REQUIRED_FIELDS:
        res = client.post("/api/checkout", json={**VALID, field: "   "})
        assert res.status_code == 400, field
        assert field in res.get_json()["error"], field


def test_checkout_rejects_an_unknown_tier():
    res = client.post("/api/checkout", json={**VALID, "tier": "t9"})
    assert res.status_code == 400
    assert res.get_json()["error"] == "Unknown tier."


def test_checkout_saves_the_booking_and_returns_a_reference():
    before = count_bookings()
    body = client.post("/api/checkout", json=VALID).get_json()

    assert body["ok"] is True
    assert body["reference"].startswith("CPK-")
    assert body["tier_label"] == "T2: Build the core product"
    assert count_bookings() == before + 1

    row = fetch(body["reference"])
    assert row["company_name"] == "Northline Traders"
    assert row["tier"] == "t2"
    assert row["notes"].startswith("Outbound is running")


def test_honeypot_looks_successful_but_stores_nothing():
    before = count_bookings()
    body = client.post("/api/checkout", json={**VALID, "website": "http://spam.example"}).get_json()

    assert body["ok"] is True          # the bot must not learn it was caught
    assert count_bookings() == before  # ...but nothing reached the database


def test_a_colliding_reference_never_overwrites_a_booking():
    original = circlpk.make_reference
    circlpk.make_reference = lambda: "CPK-FIXED-0001"
    circlpk.app.logger.disabled = True  # the 500 below is on purpose; don't print its traceback
    try:
        first = client.post("/api/checkout", json=VALID).get_json()
        assert first["reference"] == "CPK-FIXED-0001"

        before = count_bookings()
        second = client.post("/api/checkout", json=VALID)  # every retry collides
        assert second.status_code == 500
        assert count_bookings() == before
    finally:
        circlpk.make_reference = original
        circlpk.app.logger.disabled = False


def test_chat_answers_without_an_api_key():
    reply = client.post("/api/consultancy", json={"message": "What is an ICP?"}).get_json()["reply"]
    assert "ideal customer profile" in reply.lower()

    blank = client.post("/api/consultancy", json={"message": "   "}).get_json()["reply"]
    assert blank, "an empty message must still get a reply, not an empty bubble"


# Every data-prompt on the consultancy page, with a phrase only the right
# knowledge-base entry produces. These are the questions the site puts in front
# of visitors, so a wrong answer here is the most visible failure the bot has.
PROMPT_CHIPS = [
    ("What is an ICP and why does my business need one?", "ideal customer profile"),
    ("What's the difference between your T1 and T2?", "builds the replacement system"),
    ("My cold outreach gets replies but no bookings, what's going wrong?", "lighter first ask"),
    ("How is a prospect list different from a lead list?", "not filtered for fit"),
    ("How do I handle the objection 'we already have someone doing this'?", "objection handling doc"),
]


def test_every_prompt_chip_gets_the_right_answer():
    for question, expected in PROMPT_CHIPS:
        reply = client.post("/api/consultancy", json={"message": question}).get_json()["reply"]
        assert expected in reply.lower(), f"{question!r} answered with: {reply[:90]}..."


def test_admin_needs_the_password():
    client.post("/api/checkout", json=VALID)  # make sure there is something to list

    assert client.get("/admin/bookings").status_code == 401
    assert client.get("/admin/bookings", headers=basic("wrong")).status_code == 401

    page = client.get("/admin/bookings", headers=basic("test-password"))
    assert page.status_code == 200
    assert b"Northline Traders" in page.data

    export = client.get("/admin/bookings.csv", headers=basic("test-password"))
    assert export.status_code == 200
    assert export.data.splitlines()[0].startswith(b"reference,created_at,tier")


def test_admin_does_not_exist_without_a_configured_password():
    circlpk.ADMIN_PASSWORD = ""
    try:
        assert client.get("/admin/bookings").status_code == 404
        assert client.get("/admin/bookings.csv").status_code == 404
    finally:
        circlpk.ADMIN_PASSWORD = "test-password"


if __name__ == "__main__":
    checks = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for name, fn in checks:
        fn()
        print(f"  ok   {name}")
    print(f"\n{len(checks)} checks passed.")
