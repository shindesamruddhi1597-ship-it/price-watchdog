"""
DATABASE (the agent's notebook)
-------------------------------
SQLite = one file (watchdog.db). Tables:
  competitors  the 10 companies we watch (stable text IDs)
  settings     the alert threshold
  snapshots    EVERY check we ever made: what we saw, what we decided, why, where/when
  alerts       real price changes waiting for human approval (+ what was approved/executed/verified)
  price_sheet  the INTERNAL price sheet. Competitor rows can be updated (after approval).
               Our own storefront rows are PROTECTED and can never be written.
  sheet_log    audit trail of every sheet write
"""
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
# Use the project folder if writable, otherwise a temp folder (some hosts are read-only)
DATA_DIR = _HERE if os.access(_HERE, os.W_OK) else os.path.join(tempfile.gettempdir(), "pricewatchdog")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "watchdog.db")

# Where competitor pages are read from:
#   "http://127.0.0.1:5001"  the standalone mock site (python mock_site/app.py)
#   "mock"                   the same fake competitors built into this program (used by the dashboard)
BASE = "http://127.0.0.1:5001"

OWN_OWNER = "our-storefront"
SEED_OWN = [("Starter", 10.0), ("Pro", 30.0), ("Business", 80.0)]

SEED_COMPETITORS = [
    ("acmesoft", "AcmeSoft"), ("betasoft", "BetaSoft"), ("cloudnine", "CloudNine"),
    ("datadash", "DataDash"), ("evergreen", "Evergreen"), ("fluxhq", "FluxHQ"),
    ("gridly", "Gridly"), ("hivework", "HiveWork"), ("ironleaf", "IronLeaf"),
    ("jetstack", "JetStack"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS competitors (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL, active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id TEXT, plan TEXT, plan_label TEXT,
    raw_price TEXT, amount REAL, currency TEXT, period TEXT, status TEXT,
    decision TEXT, reason TEXT, is_baseline INTEGER,
    source_url TEXT, retrieved_at TEXT, screenshot_path TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id TEXT, plan TEXT, before_price TEXT, after_price TEXT,
    after_amount REAL, after_currency TEXT, after_period TEXT,
    pct_change REAL, reason TEXT, source_url TEXT, detected_at TEXT, screenshot_path TEXT,
    approval_status TEXT DEFAULT 'pending', approved_at TEXT,
    payload TEXT, executed_at TEXT, verification TEXT, verification_detail TEXT
);
CREATE TABLE IF NOT EXISTS price_sheet (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT, owner_type TEXT, plan TEXT,
    price_text TEXT, amount REAL, currency TEXT, period TEXT,
    protected INTEGER DEFAULT 0,
    evidence_url TEXT, evidence_date TEXT, evidence_alert_id INTEGER, evidence_screenshot TEXT,
    updated_at TEXT,
    UNIQUE(owner, plan)
);
CREATE TABLE IF NOT EXISTS sheet_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT, plan TEXT, old_price TEXT, new_price TEXT, alert_id INTEGER, at TEXT
);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(alerts)")]
        if cols and "payload" not in cols:  # database from an older version: start fresh
            conn.executescript(
                "DROP TABLE IF EXISTS competitors; DROP TABLE IF EXISTS settings;"
                "DROP TABLE IF EXISTS snapshots; DROP TABLE IF EXISTS alerts;"
            )
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM competitors").fetchone()[0] == 0:
            for cid, name in SEED_COMPETITORS:
                conn.execute("INSERT INTO competitors (id, name, url) VALUES (?, ?, ?)",
                             (cid, name, f"/c/{cid}/pricing"))
        conn.execute("INSERT OR IGNORE INTO settings VALUES ('threshold_pct', '5')")
        if conn.execute("SELECT COUNT(*) FROM price_sheet WHERE owner_type='own'").fetchone()[0] == 0:
            for plan, amount in SEED_OWN:
                conn.execute(
                    "INSERT INTO price_sheet (owner, owner_type, plan, price_text, amount, currency, period,"
                    " protected, updated_at) VALUES (?, 'own', ?, ?, ?, 'USD', 'monthly', 1, ?)",
                    (OWN_OWNER, plan, f"${amount:g}", amount, "seeded"),
                )


def reset_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()


def competitor_url(cid):
    return f"mock://{cid}/pricing" if BASE == "mock" else f"{BASE}/c/{cid}/pricing"


def get_competitors():
    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM competitors WHERE active = 1")]
    for r in rows:
        r["url"] = competitor_url(r["id"])
    return rows


def competitor_names():
    return {c["id"]: c["name"] for c in get_competitors()}


def get_threshold():
    with connect() as conn:
        return float(conn.execute("SELECT value FROM settings WHERE key='threshold_pct'").fetchone()[0])


def set_threshold(value):
    with connect() as conn:
        conn.execute("UPDATE settings SET value=? WHERE key='threshold_pct'", (str(value),))


# ---------------------------------------------------------------- snapshots
def latest_baseline(competitor_id, plan):
    """The last ACCEPTED price for this plan (currency switches and 'Contact sales' don't count)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT plan, raw_price, amount, currency, period, status FROM snapshots "
            "WHERE competitor_id=? AND plan=? AND is_baseline=1 ORDER BY id DESC LIMIT 1",
            (competitor_id, plan),
        ).fetchone()
    return dict(row) if row else None


def save_snapshot(competitor_id, plan, plan_label, new, result, evidence, screenshot_path=None):
    # Only trusted prices become the next "before" value. Small sub-threshold drifts
    # don't, so slow creeping increases can still add up to an alert.
    is_baseline = result["decision"] in ("NEW_BASELINE", "REAL_CHANGE") or (
        result["decision"] == "NO_CHANGE" and not result["pct_change"]
    )
    with connect() as conn:
        conn.execute(
            "INSERT INTO snapshots (competitor_id, plan, plan_label, raw_price, amount, currency, period,"
            " status, decision, reason, is_baseline, source_url, retrieved_at, screenshot_path)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (competitor_id, plan, plan_label, new["raw_price"], new["amount"], new["currency"],
             new["period"], new["status"], result["decision"], result["reason"], int(is_baseline),
             evidence["source_url"], evidence["retrieved_at"], screenshot_path),
        )


def save_failure(competitor_id, url, decision, reason):
    """Record a failed fetch or unreadable page, so it stays visible instead of vanishing."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO snapshots (competitor_id, plan, plan_label, status, decision, reason,"
            " is_baseline, source_url, retrieved_at) VALUES (?,?,?,?,?,?,0,?,?)",
            (competitor_id, "-", "-", decision.lower(), decision, reason, url, now()),
        )


def latest_snapshots():
    """Most recent check per competitor and plan (a stale fetch failure is hidden once a newer good check exists)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT s.*, c.name AS competitor FROM snapshots s JOIN competitors c ON c.id = s.competitor_id "
            "WHERE s.id IN (SELECT MAX(id) FROM snapshots GROUP BY competitor_id, plan) "
            "AND (s.plan != '-' OR s.id > (SELECT COALESCE(MAX(id), 0) FROM snapshots "
            "     WHERE competitor_id = s.competitor_id AND plan != '-')) "
            "ORDER BY c.name, s.plan"
        )
        return [dict(r) for r in rows]


def recent_snapshots(limit=60):
    with connect() as conn:
        rows = conn.execute(
            "SELECT s.*, c.name AS competitor FROM snapshots s JOIN competitors c ON c.id = s.competitor_id "
            "ORDER BY s.id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]


def count_snapshots():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]


# ---------------------------------------------------------------- alerts
def save_alert(competitor_id, result, evidence, screenshot_path=None, new=None):
    new = new or {}
    with connect() as conn:
        dup = conn.execute(
            "SELECT id FROM alerts WHERE competitor_id=? AND plan=? AND before_price=? AND after_price=?"
            " AND approval_status='pending'",
            (competitor_id, result["plan"], result["before"], result["after"]),
        ).fetchone()
        if dup:
            return dup["id"]  # no duplicate alerts on retries
        cur = conn.execute(
            "INSERT INTO alerts (competitor_id, plan, before_price, after_price, after_amount, after_currency,"
            " after_period, pct_change, reason, source_url, detected_at, screenshot_path)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (competitor_id, result["plan"], result["before"], result["after"], new.get("amount"),
             new.get("currency"), new.get("period"), result["pct_change"], result["reason"],
             evidence["source_url"], evidence["retrieved_at"], screenshot_path),
        )
        return cur.lastrowid


def list_alerts(status=None):
    with connect() as conn:
        if status:
            rows = conn.execute("SELECT * FROM alerts WHERE approval_status=? ORDER BY id DESC", (status,))
        else:
            rows = conn.execute("SELECT * FROM alerts ORDER BY id DESC")
        return [dict(r) for r in rows]


def get_alert(alert_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
    return dict(row) if row else None


def claim_alert(alert_id, payload_json):
    """Atomically move pending -> approved. Returns False if it was already handled (retry-safe)."""
    with connect() as conn:
        cur = conn.execute(
            "UPDATE alerts SET approval_status='approved', approved_at=?, payload=? "
            "WHERE id=? AND approval_status='pending'", (now(), payload_json, alert_id))
        return cur.rowcount == 1


def reject_alert(alert_id):
    with connect() as conn:
        cur = conn.execute("UPDATE alerts SET approval_status='rejected', approved_at=? "
                           "WHERE id=? AND approval_status='pending'", (now(), alert_id))
        return cur.rowcount == 1


def mark_executed(alert_id):
    with connect() as conn:
        conn.execute("UPDATE alerts SET executed_at=? WHERE id=?", (now(), alert_id))


def set_verification(alert_id, status, detail):
    with connect() as conn:
        conn.execute("UPDATE alerts SET verification=?, verification_detail=? WHERE id=?",
                     (status, detail, alert_id))


# ---------------------------------------------------------------- internal price sheet
def sheet_seed(competitor_id, plan, new, evidence, screenshot_path=None):
    """First time we see a competitor plan: create its sheet row (never overwrites)."""
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO price_sheet (owner, owner_type, plan, price_text, amount, currency, period,"
            " protected, evidence_url, evidence_date, evidence_screenshot, updated_at)"
            " VALUES (?, 'competitor', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
            (competitor_id, plan, new["raw_price"], new["amount"], new["currency"], new["period"],
             evidence["source_url"], evidence["retrieved_at"], screenshot_path, now()),
        )


def get_sheet(owner_type=None):
    with connect() as conn:
        q = ("SELECT p.*, COALESCE(c.name, 'Our storefront') AS owner_name FROM price_sheet p "
             "LEFT JOIN competitors c ON c.id = p.owner ")
        if owner_type:
            rows = conn.execute(q + "WHERE p.owner_type=? ORDER BY owner_name, p.plan", (owner_type,))
        else:
            rows = conn.execute(q + "ORDER BY owner_name, p.plan")
        return [dict(r) for r in rows]


def get_sheet_row(owner, plan):
    with connect() as conn:
        row = conn.execute("SELECT * FROM price_sheet WHERE owner=? AND plan=?", (owner, plan)).fetchone()
    return dict(row) if row else None


def sheet_fingerprint(owner_type="own"):
    """A short hash of every row of one kind. If anything in it is touched, the hash changes."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT owner, plan, price_text, amount, currency, period, protected, updated_at "
            "FROM price_sheet WHERE owner_type=? ORDER BY owner, plan", (owner_type,)).fetchall()
    return hashlib.sha256(json.dumps([list(r) for r in rows]).encode()).hexdigest()[:16]


def write_sheet_row(owner, plan, price_text, amount, currency, period, alert_id, url, date, screenshot):
    """The ONLY function that writes to the price sheet. It refuses to touch our own storefront."""
    if owner == OWN_OWNER:
        raise PermissionError("Blocked: our own storefront prices are protected and can never be written.")
    with connect() as conn:
        row = conn.execute("SELECT * FROM price_sheet WHERE owner=? AND plan=?", (owner, plan)).fetchone()
        if row is not None and (row["protected"] or row["owner_type"] != "competitor"):
            raise PermissionError("Blocked: this sheet row is protected.")
        old = row["price_text"] if row else None
        if row:
            conn.execute(
                "UPDATE price_sheet SET price_text=?, amount=?, currency=?, period=?, evidence_url=?,"
                " evidence_date=?, evidence_alert_id=?, evidence_screenshot=?, updated_at=? WHERE id=?",
                (price_text, amount, currency, period, url, date, alert_id, screenshot, now(), row["id"]))
        else:
            conn.execute(
                "INSERT INTO price_sheet (owner, owner_type, plan, price_text, amount, currency, period,"
                " protected, evidence_url, evidence_date, evidence_alert_id, evidence_screenshot, updated_at)"
                " VALUES (?, 'competitor', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)",
                (owner, plan, price_text, amount, currency, period, url, date, alert_id, screenshot, now()))
        conn.execute("INSERT INTO sheet_log (owner, plan, old_price, new_price, alert_id, at) VALUES (?,?,?,?,?,?)",
                     (owner, plan, old, price_text, alert_id, now()))


def list_sheet_log(limit=50):
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM sheet_log ORDER BY id DESC LIMIT ?", (limit,))]
