"""
APPROVAL, ACTION and VERIFICATION
---------------------------------
approve_alert(): a human approved -> store the approved version -> write to the internal price sheet.
verify():        a SEPARATE check that re-reads the sheet and confirms what was written matches
                 what was approved, and that our own storefront rows were not touched.
Approving the same alert twice does nothing the second time (idempotent).
"""
import json

import db


def approve_alert(alert_id):
    alert = db.get_alert(alert_id)
    if alert is None:
        return {"ok": False, "message": "Alert not found."}

    payload = {
        "alert_id": alert_id,
        "owner": alert["competitor_id"],
        "plan": alert["plan"],
        "price_text": alert["after_price"],
        "amount": alert["after_amount"],
        "currency": alert["after_currency"],
        "period": alert["after_period"],
        "evidence_url": alert["source_url"],
        "evidence_date": alert["detected_at"],
        "screenshot": alert["screenshot_path"],
        "own_fp_before": db.sheet_fingerprint("own"),
    }
    # Claim first: only ONE caller can move pending -> approved, so retries cannot write twice
    if not db.claim_alert(alert_id, json.dumps(payload)):
        return {"ok": False, "message": "Already processed. Nothing was written again (duplicate execution prevented)."}

    try:
        db.write_sheet_row(payload["owner"], payload["plan"], payload["price_text"], payload["amount"],
                           payload["currency"], payload["period"], alert_id, payload["evidence_url"],
                           payload["evidence_date"], payload["screenshot"])
        db.mark_executed(alert_id)
    except Exception as e:
        db.set_verification(alert_id, "failed", f"Write failed: {e}")
        return {"ok": False, "message": f"Write failed: {e}"}
    return verify(alert_id)


def verify(alert_id):
    """Independent check of the real result. Failures stay visible."""
    alert = db.get_alert(alert_id)
    payload = json.loads(alert["payload"] or "{}")
    problems = []
    row = db.get_sheet_row(payload.get("owner"), payload.get("plan"))
    if row is None:
        problems.append("approved row is missing from the sheet")
    else:
        if row["price_text"] != payload["price_text"]:
            problems.append(f"sheet shows {row['price_text']} but {payload['price_text']} was approved")
        if row["evidence_alert_id"] != alert_id:
            problems.append("sheet row is not linked to this alert")
        if not row["evidence_date"]:
            problems.append("sheet row has no dated evidence")
    if db.sheet_fingerprint("own") != payload.get("own_fp_before"):
        problems.append("OUR OWN STOREFRONT ROWS CHANGED")

    if problems:
        detail, status = "; ".join(problems), "failed"
    else:
        detail = (f"Sheet row {row['price_text']} (evidence dated {row['evidence_date']} UTC). "
                  "Own storefront rows unchanged.")
        status = "verified"
    db.set_verification(alert_id, status, detail)
    return {"ok": status == "verified", "message": ("Updated and verified. " if status == "verified" else "Verification FAILED: ") + detail}


def reject_alert(alert_id):
    if db.reject_alert(alert_id):
        return {"ok": True, "message": "Rejected. The price sheet was not changed."}
    return {"ok": False, "message": "Already processed."}
