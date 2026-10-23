"""
THE 4 OFFICIAL TEST CASES
-------------------------
Each test starts from a clean temporary notebook and normal competitor pages, saves a baseline,
creates the scenario, runs the agent, and records input / expected / actual / evidence.
Your live demo data is not touched, and your simulated competitors are restored afterwards.

    python testcases.py
"""
import os
import tempfile

import approval
import agent
import db
import proof
from mock_site.app import modes as mock_modes


def _setup():
    db.DB_PATH = os.path.join(tempfile.gettempdir(), "watchdog_tests.db")
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()
    for k in mock_modes:
        mock_modes[k] = "normal"
    agent.run_all(verbose=False)  # baseline from normal pages


def _latest(competitor_id):
    return {s["plan"]: s for s in db.latest_snapshots() if s["competitor"].lower() == competitor_id}


def _result(tc, scenario, inp, expected, actual, passed, evidence, images=()):
    return {"tc": tc, "scenario": scenario, "input": inp, "expected": expected, "actual": actual,
            "passed": bool(passed), "evidence": evidence, "images": [i for i in images if i]}


def tc1():
    _setup()
    mock_modes["betasoft"] = "price_changed"
    agent.run_all(verbose=False)
    alert = next((a for a in db.list_alerts() if a["competitor_id"] == "betasoft" and a["plan"] == "Pro"), None)
    shot_ok = bool(alert and alert["screenshot_path"] and os.path.exists(proof.abs_path(alert["screenshot_path"])))
    passed = bool(alert and alert["detected_at"] and shot_ok and alert["before_price"] == "$39" and alert["after_price"] == "$47")
    actual = (f"Alert #{alert['id']}: BetaSoft Pro {alert['before_price']} -> {alert['after_price']} "
              f"({alert['pct_change']:+.1f}%), dated {alert['detected_at']} UTC, screenshot saved") if alert else "No alert raised"
    ev = []
    if alert:
        ev = [f"Reason: {alert['reason']}", f"Source: {alert['source_url']}",
              "The page called this tier 'Professional'; the agent matched it to 'Pro' before comparing.",
              f"Screenshot file: {alert['screenshot_path']}"]
    return _result("TC1", "Comparable tier price changes",
                   "BetaSoft pricing page: Professional tier goes $39 -> $47 per month",
                   "Dated alert with screenshot", actual, passed, ev, [proof.abs_path(alert["screenshot_path"])] if alert else [])


def tc2():
    _setup()
    mock_modes["datadash"] = "inr"
    agent.run_all(verbose=False)
    snaps = _latest("datadash")
    all_switch = len(snaps) == 3 and all(s["decision"] == "CURRENCY_SWITCH" for s in snaps.values())
    no_alert = not any(a["competitor_id"] == "datadash" for a in db.list_alerts())
    passed = all_switch and no_alert
    actual = ("All 3 DataDash plans classified CURRENCY_SWITCH; 0 alerts raised" if passed
              else "Currency switch was mishandled")
    ev = [f"{s['plan']}: shown as {s['raw_price']} -> {s['decision']}: {s['reason']}" for s in snaps.values()]
    imgs = [proof.abs_path(next(iter(snaps.values()))["screenshot_path"])] if snaps else []
    return _result("TC2", "Page switches from USD to INR",
                   "DataDash pricing page now shows rupee prices (same prices, different currency)",
                   "Not reported as a price change", actual, passed, ev, imgs)


def tc3():
    _setup()
    sheet_before = db.get_sheet_row("fluxhq", "Pro")["price_text"]
    mock_modes["fluxhq"] = "contact_sales"
    agent.run_all(verbose=False)
    pro = _latest("fluxhq").get("Pro")
    sheet_after = db.get_sheet_row("fluxhq", "Pro")["price_text"]
    no_alert = not any(a["competitor_id"] == "fluxhq" for a in db.list_alerts())
    passed = bool(pro and pro["decision"] == "PRICE_UNAVAILABLE" and pro["raw_price"] == "Contact sales"
                  and no_alert and sheet_before == sheet_after)
    actual = ("FluxHQ Pro marked PRICE_UNAVAILABLE; no alert; price sheet left at " + sheet_after) if passed else "Not handled correctly"
    ev = [f"Page showed: '{pro['raw_price']}'" if pro else "No data", f"Reason: {pro['reason']}" if pro else ""]
    return _result("TC3", "'Contact sales' only",
                   "FluxHQ pricing page: Pro plan shows 'Contact sales' instead of a price",
                   "Marked price unavailable", actual, passed, ev,
                   [proof.abs_path(pro["screenshot_path"])] if pro else [])


def tc4():
    _setup()
    mock_modes["betasoft"] = "price_changed"
    agent.run_all(verbose=False)
    alert = next(a for a in db.list_alerts("pending") if a["competitor_id"] == "betasoft")
    own_before = db.sheet_fingerprint("own")
    first = approval.approve_alert(alert["id"])
    second = approval.approve_alert(alert["id"])  # retry must not write again
    row = db.get_sheet_row("betasoft", "Pro")
    writes = [l for l in db.list_sheet_log() if l["owner"] == "betasoft" and l["plan"] == "Pro"]
    own_after = db.sheet_fingerprint("own")
    try:
        db.write_sheet_row(db.OWN_OWNER, "Pro", "$1", 1, "USD", "monthly", 0, "x", "x", None)
        blocked = False
    except PermissionError:
        blocked = True
    own_after_attack = db.sheet_fingerprint("own")
    passed = (first["ok"] and row["price_text"] == "$47" and own_before == own_after == own_after_attack
              and not second["ok"] and len(writes) == 1 and blocked)
    actual = ("Competitor row updated to $47 with dated evidence and verified; own storefront unchanged; "
              "retry blocked; direct write to storefront blocked") if passed else "A safety check failed"
    ev = [f"Approval result: {first['message']}",
          f"Retry result: {second['message']}",
          f"Sheet writes for BetaSoft Pro: {len(writes)} (expected 1)",
          f"Own storefront fingerprint before/after: {own_before} / {own_after}",
          f"Direct write to our storefront attempted -> {'BLOCKED' if blocked else 'ALLOWED (bad!)'}"]
    return _result("TC4", "Internal sheet updated",
                   "Approve the BetaSoft Pro alert, approve it again (retry), then try to write to our own storefront row",
                   "Own storefront prices never touched", actual, passed, ev, [proof.abs_path(alert["screenshot_path"])])


def run_all():
    original = (db.DB_PATH, db.BASE)
    saved_modes = dict(mock_modes)
    db.BASE = "mock"
    try:
        return [tc1(), tc2(), tc3(), tc4()]
    finally:
        db.DB_PATH, db.BASE = original
        mock_modes.clear()
        mock_modes.update(saved_modes)


if __name__ == "__main__":
    for r in run_all():
        print(f"{r['tc']} [{'PASS' if r['passed'] else 'FAIL'}] {r['scenario']}")
        print("   expected:", r["expected"])
        print("   actual:  ", r["actual"])
        for line in r["evidence"]:
            print("   -", line)
