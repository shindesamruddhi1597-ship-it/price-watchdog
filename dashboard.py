"""
DASHBOARD  (run with:  streamlit run dashboard.py)
"""
import pandas as pd
import streamlit as st

import db

db.BASE = "mock"  # read the built-in fake competitors directly (no second server needed)

import agent  # noqa: E402
import approval  # noqa: E402
import proof  # noqa: E402
import testcases  # noqa: E402
from mock_site.app import COMPETITORS, MODES, modes as mock_modes  # noqa: E402

st.set_page_config(page_title="Competitor Price Watchdog", layout="wide")
db.init_db()
names = db.competitor_names()

st.title("Competitor Price Watchdog")
st.caption("An agent that watches competitor pricing pages, alerts only on REAL price changes, "
           "and updates the internal price sheet only after a human approves.")

page = st.sidebar.radio("Go to", ["Dashboard", "Approvals", "Price sheet", "Simulator", "Test cases", "Audit log"],
                        key="page")
st.sidebar.markdown("---")
st.sidebar.caption("Competitors here are simulated so every scenario can be shown on demand. "
                   "Use **Simulator** to change their pricing pages.")


# ----------------------------------------------------------------------------- Dashboard
if page == "Dashboard":
    c1, c2 = st.columns([2, 1])
    with c1:
        if st.button("Run price check on all competitors", type="primary", key="run_check"):
            with st.spinner("Checking all competitor pricing pages..."):
                rows = agent.run_all(verbose=False)
            counts = {}
            for _, _, decision, _ in rows:
                counts[decision] = counts.get(decision, 0) + 1
            st.session_state["last_run"] = counts
        if "last_run" in st.session_state:
            st.success("Last check finished: " + ", ".join(f"{k}: {v}" for k, v in st.session_state["last_run"].items()))
    with c2:
        thr = st.number_input("Alert threshold (%)", min_value=0.1, max_value=100.0,
                              value=float(db.get_threshold()), step=0.5, key="threshold")
        if thr != db.get_threshold():
            db.set_threshold(thr)

    m1, m2, m3 = st.columns(3)
    m1.metric("Competitors watched", len(names))
    m2.metric("Alerts waiting for approval", len(db.list_alerts("pending")))
    m3.metric("Checks recorded", db.count_snapshots())

    snaps = db.latest_snapshots()
    if not snaps:
        st.info("No checks yet. Click **Run price check on all competitors** to save the first baseline.")
    else:
        attention = [s for s in snaps if s["decision"] in ("PRICE_UNAVAILABLE", "UNCERTAIN", "FETCH_FAILED")]
        if attention:
            st.subheader("Needs attention (unresolved)")
            st.dataframe(pd.DataFrame([{"Competitor": s["competitor"], "Plan": s["plan"], "Status": s["decision"],
                                        "Why": s["reason"]} for s in attention]))
        st.subheader("Latest result for every competitor plan")
        st.dataframe(pd.DataFrame([{
            "Competitor": s["competitor"], "Plan": s["plan"], "Price on page": s["raw_price"],
            "Decision": s["decision"], "Why": s["reason"], "Checked (UTC)": s["retrieved_at"],
        } for s in snaps]))

    with st.expander("Demo controls"):
        if st.button("Reset everything (database and simulated competitors)", key="reset_all"):
            db.reset_db()
            for k in mock_modes:
                mock_modes[k] = "normal"
            st.session_state.pop("last_run", None)
            st.rerun()


# ----------------------------------------------------------------------------- Approvals
elif page == "Approvals":
    st.header("Alerts waiting for approval")
    st.caption("Nothing is written to the internal price sheet until you click Approve. "
               "Our own storefront prices can never be changed by the agent.")
    msg = st.session_state.pop("approval_msg", None)
    if msg:
        (st.success if msg[0] else st.error)(msg[1])

    pending = db.list_alerts("pending")
    if not pending:
        st.info("No pending alerts. Run a check on the Dashboard after changing a competitor in the Simulator.")
    for a in pending:
        name = names.get(a["competitor_id"], a["competitor_id"])
        with st.container(border=True):
            st.markdown(f"### {name} - {a['plan']}:  {a['before_price']}  to  {a['after_price']}  ({a['pct_change']:+.1f}%)")
            st.write(a["reason"])
            st.caption(f"Source: {a['source_url']}  |  Detected: {a['detected_at']} UTC  |  Alert #{a['id']}")
            left, right = st.columns([3, 2])
            with left:
                if a["screenshot_path"]:
                    st.image(proof.abs_path(a["screenshot_path"]), width=560)
            with right:
                st.markdown("**Proposed action**")
                st.write(f"Update the internal price sheet row **{name} / {a['plan']}** from "
                         f"**{a['before_price']}** to **{a['after_price']}**, with the source and date as evidence.")
                st.write("Destination: internal price sheet (competitor rows only).")
                if st.button("Approve", key=f"approve_{a['id']}", type="primary"):
                    res = approval.approve_alert(a["id"])
                    st.session_state["approval_msg"] = (res["ok"], res["message"])
                    st.rerun()
                if st.button("Reject", key=f"reject_{a['id']}"):
                    res = approval.reject_alert(a["id"])
                    st.session_state["approval_msg"] = (res["ok"], res["message"])
                    st.rerun()

    done = [a for a in db.list_alerts() if a["approval_status"] != "pending"]
    if done:
        st.subheader("Processed alerts")
        st.dataframe(pd.DataFrame([{
            "Alert": a["id"], "Competitor": names.get(a["competitor_id"]), "Plan": a["plan"],
            "Before": a["before_price"], "After": a["after_price"], "Decision": a["approval_status"],
            "Written (UTC)": a["executed_at"], "Verification": a["verification"],
            "Verification detail": a["verification_detail"],
        } for a in done]))


# ----------------------------------------------------------------------------- Price sheet
elif page == "Price sheet":
    st.header("Internal price sheet")
    st.subheader("Competitor prices (updated only after approval, with dated evidence)")
    comp_rows = db.get_sheet("competitor")
    if comp_rows:
        st.dataframe(pd.DataFrame([{
            "Competitor": r["owner_name"], "Plan": r["plan"], "Price": r["price_text"],
            "Evidence source": r["evidence_url"], "Evidence date (UTC)": r["evidence_date"],
            "Linked alert": r["evidence_alert_id"],
        } for r in comp_rows]))
    else:
        st.info("The sheet fills with the first baseline check.")
    st.subheader("Our own storefront (protected, read-only)")
    st.dataframe(pd.DataFrame([{"Plan": r["plan"], "Price": r["price_text"], "Protected": "yes"}
                               for r in db.get_sheet("own")]))
    st.caption(f"Storefront fingerprint (changes if anything in it is touched): {db.sheet_fingerprint('own')}")


# ----------------------------------------------------------------------------- Simulator
elif page == "Simulator":
    st.header("Competitor simulator")
    st.write("Real competitors will not change prices on demand, so these 10 pricing pages are simulated. "
             "Change one here, then run a check on the Dashboard.")
    c1, c2, c3 = st.columns([2, 2, 1])
    slug = c1.selectbox("Competitor", list(COMPETITORS), format_func=lambda s: COMPETITORS[s]["name"], key="sim_comp")
    mode = c2.selectbox("Scenario", list(MODES), format_func=lambda m: MODES[m], key="sim_mode")
    c3.write("")
    if c3.button("Apply", type="primary", key="sim_apply"):
        mock_modes[slug] = mode
        st.rerun()
    if st.button("Reset all to Normal", key="sim_reset"):
        for k in mock_modes:
            mock_modes[k] = "normal"
        st.rerun()
    st.dataframe(pd.DataFrame([{"Competitor": COMPETITORS[s]["name"], "Scenario now": MODES[mock_modes[s]]}
                               for s in COMPETITORS]))
    st.subheader("What the selected page currently shows")
    from mock_site.app import plans_for
    st.dataframe(pd.DataFrame(plans_for(slug), columns=["Plan", "Price", "Billing"]))


# ----------------------------------------------------------------------------- Test cases
elif page == "Test cases":
    st.header("Official test cases")
    st.write("Runs all 4 scenarios from a clean notebook and shows input, expected result, actual result and evidence. "
             "Your live demo data is not affected.")
    if st.button("Run all 4 test cases", type="primary", key="run_tests"):
        with st.spinner("Running TC1 to TC4..."):
            st.session_state["test_results"] = testcases.run_all()
    results = st.session_state.get("test_results")
    if results:
        passed = sum(r["passed"] for r in results)
        (st.success if passed == len(results) else st.error)(f"{passed} of {len(results)} test cases passed")
        for r in results:
            with st.container(border=True):
                st.markdown(f"### {r['tc']} - {r['scenario']}:  {'PASS' if r['passed'] else 'FAIL'}")
                st.markdown(f"**Input:** {r['input']}")
                st.markdown(f"**Expected:** {r['expected']}")
                st.markdown(f"**Actual:** {r['actual']}")
                for line in r["evidence"]:
                    if line:
                        st.write("- " + line)
                for img in r["images"]:
                    st.image(img, width=520)


# ----------------------------------------------------------------------------- Audit log
elif page == "Audit log":
    st.header("Audit log")
    st.subheader("Every check the agent made (newest first)")
    st.dataframe(pd.DataFrame([{
        "When (UTC)": s["retrieved_at"], "Competitor": s["competitor"], "Plan": s["plan"],
        "Price seen": s["raw_price"], "Decision": s["decision"], "Why": s["reason"], "Source": s["source_url"],
    } for s in db.recent_snapshots()]))
    st.subheader("Every write to the price sheet")
    st.dataframe(pd.DataFrame([{
        "When (UTC)": l["at"], "Owner": l["owner"], "Plan": l["plan"], "Old": l["old_price"],
        "New": l["new_price"], "Alert": l["alert_id"],
    } for l in db.list_sheet_log()]))
