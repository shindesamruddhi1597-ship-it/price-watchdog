"""
THE AGENT
---------
Loops over every competitor: fetch -> extract -> compare with the notebook -> decide -> save.
Real price changes become pending alerts (with an evidence snapshot). Nothing touches the
price sheet until a human approves (see approval.py).

    python agent.py            run one check of all competitors
    python agent.py --reset    wipe the notebook first (fresh start)
"""
import sys

import db
import proof
from decision import decide, normalise_plan_name
from extractor import extract_prices


def check_competitor(comp, threshold):
    rows = []
    try:
        plans, evidence = extract_prices(comp["url"])
    except Exception as e:  # a failed fetch is NOT a price change
        reason = f"Could not fetch page: {str(e)[:100]}"
        db.save_failure(comp["id"], comp["url"], "FETCH_FAILED", reason)
        return [(comp["name"], "-", "FETCH_FAILED", reason)]

    snapshot_path = proof.render_snapshot(comp["name"], plans, evidence)

    if not plans:
        reason = "Page loaded but no plans could be read."
        db.save_failure(comp["id"], comp["url"], "UNCERTAIN", reason)
        return [(comp["name"], "-", "UNCERTAIN", reason)]

    for p in plans:
        plan = normalise_plan_name(p["plan"])
        old = db.latest_baseline(comp["id"], plan)
        result = decide(old, p, threshold)
        db.save_snapshot(comp["id"], plan, p["plan"], p, result, evidence, snapshot_path)
        if result["decision"] == "NEW_BASELINE":
            db.sheet_seed(comp["id"], plan, p, evidence, snapshot_path)
        if result["alert"]:
            db.save_alert(comp["id"], result, evidence, snapshot_path, new=p)
        rows.append((comp["name"], plan, result["decision"], result["reason"]))
    return rows


def run_all(verbose=True):
    db.init_db()
    threshold = db.get_threshold()
    competitors = db.get_competitors()
    all_rows = []
    for comp in competitors:
        all_rows += check_competitor(comp, threshold)

    if verbose:
        counts = {}
        for _, _, decision, _ in all_rows:
            counts[decision] = counts.get(decision, 0) + 1
        print(f"Checked {len(competitors)} competitors, threshold {threshold}%")
        print("Summary:", counts)
        print()
        for name, plan, decision, reason in all_rows:
            if decision not in ("NO_CHANGE", "NEW_BASELINE"):
                print(f"{name:10} {plan:9} {decision:18} {reason}")
        print(f"\nPending alerts waiting for approval: {len(db.list_alerts('pending'))}")
    return all_rows


if __name__ == "__main__":
    if "--reset" in sys.argv:
        db.reset_db()
        print("Notebook wiped.\n")
    run_all()
