import requests

from decision import decide, normalise_plan_name
from extractor import extract_prices

MOCK = "http://127.0.0.1:5001"
PRICING_URL = f"{MOCK}/pricing"


def set_scenario(mode: str):
    requests.get(f"{MOCK}/set/{mode}", timeout=10)


def snapshot():
    plans, _ = extract_prices(PRICING_URL)
    return {normalise_plan_name(p["plan"]): p for p in plans}


set_scenario("normal")
baseline = snapshot()
print("Baseline saved:", {k: v["raw_price"] for k, v in baseline.items()})

for mode in ["price_changed", "inr", "contact_sales"]:
    set_scenario(mode)
    current = snapshot()
    print(f"\n=== Scenario: {mode} ===")
    for plan, new in current.items():
        r = decide(baseline.get(plan), new, threshold_pct=5.0)
        if r["decision"] == "NO_CHANGE":
            continue
        flag = "ALERT" if r["alert"] else "no alert"
        print(f"[{flag}] {plan}: {r['decision']}")
        print(f"         before={r['before']}  after={r['after']}")
        print(f"         why: {r['reason']}")

set_scenario("normal")