APPROX_RATES_TO_USD = {"USD": 1.0, "INR": 1 / 83, "EUR": 1.08, "GBP": 1.27}

PLAN_ALIASES = {
    "basic": "Starter",
    "starter": "Starter",
    "lite": "Starter",
    "pro": "Pro",
    "professional": "Pro",
    "plus": "Pro",
    "business": "Business",
    "team": "Business",
    "enterprise": "Enterprise",
}


def normalise_plan_name(name: str) -> str:
    return PLAN_ALIASES.get(name.strip().lower(), name.strip())


def to_monthly(amount: float, period: str):
    if period == "monthly":
        return amount
    if period == "yearly":
        return round(amount / 12, 2)
    return None


def decide(old: dict, new: dict, threshold_pct: float = 5.0) -> dict:
    plan = normalise_plan_name(new["plan"])

    def result(decision, reason, pct=None):
        return {
            "plan": plan,
            "decision": decision,
            "reason": reason,
            "before": old["raw_price"] if old else None,
            "after": new["raw_price"],
            "pct_change": pct,
            "alert": decision == "REAL_CHANGE",
        }

    # TC3: no public price on the page
    if new["status"] == "price_unavailable":
        return result("PRICE_UNAVAILABLE", "Page shows no public price (e.g. 'Contact sales'). Not guessing.")

    # Price found but we cannot tell what it means -> refuse to guess
    if new["amount"] is None or new["currency"] is None or new["period"] is None:
        return result("UNCERTAIN", "Price found but currency or billing period is missing.")

    # First time we see this plan, or the old record had no price
    if old is None or old["status"] != "ok":
        return result("NEW_BASELINE", "No previous price on record. Saved as baseline.")

    # TC2: currency changed. A display change, not a price change.
    if old["currency"] != new["currency"]:
        rate = APPROX_RATES_TO_USD.get(new["currency"])
        hint = ""
        if rate and old["currency"] == "USD":
            hint = f" (about ${new['amount'] * rate:,.0f} USD at an approximate rate, for information only)"
        return result(
            "CURRENCY_SWITCH",
            f"Currency changed {old['currency']} -> {new['currency']}{hint}. Not reported as a price change.",
        )

    # Same currency: normalise billing period, then compare
    old_m = to_monthly(old["amount"], old["period"])
    new_m = to_monthly(new["amount"], new["period"])
    if old_m is None or new_m is None or old_m == 0:
        return result("UNCERTAIN", "Cannot compare billing periods.")

    pct = round((new_m - old_m) / old_m * 100, 1)
    if abs(pct) >= threshold_pct:
        direction = "increased" if pct > 0 else "decreased"
        return result(
            "REAL_CHANGE",
            f"Monthly price {direction} {abs(pct)}% ({old_m:g} -> {new_m:g} {new['currency']}). Threshold is {threshold_pct}%.",
            pct,
        )
    return result("NO_CHANGE", f"Change of {pct}% is below the {threshold_pct}% threshold.", pct)