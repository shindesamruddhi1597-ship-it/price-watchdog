"""
EXTRACTOR
---------
Visits a pricing page and turns it into clean data. For every plan it returns:
    plan, raw_price, amount, currency, period, status ("ok" | "price_unavailable")
It never guesses. If there is no readable price, status is "price_unavailable".

URLs can be normal http(s) pages, or mock://<competitor>/pricing which reads the
built-in fake competitors directly (no second server needed).
"""
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

CURRENCY_SYMBOLS = {"$": "USD", "₹": "INR", "€": "EUR", "£": "GBP"}


def parse_price(raw_price: str):
    text = raw_price.strip()
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in text:
            digits = re.sub(r"[^\d.]", "", text.replace(",", ""))
            if digits:
                return float(digits), code
    return None, None


def parse_period(text: str):
    t = text.lower()
    if "month" in t or "/mo" in t:
        return "monthly"
    if "year" in t or "annual" in t or "/yr" in t:
        return "yearly"
    return None


def fetch_html(url: str):
    if url.startswith("mock://"):
        slug = url[len("mock://"):].split("/")[0]
        from mock_site.app import app as mock_app  # the built-in fake competitors

        response = mock_app.test_client().get(f"/c/{slug}/pricing")
        if response.status_code != 200:
            raise RuntimeError(f"mock competitor returned HTTP {response.status_code}")
        return response.get_data(as_text=True), response.status_code
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return response.text, response.status_code


def extract_prices(url: str):
    """Fetch the page and return (plans, evidence)."""
    html, status_code = fetch_html(url)
    evidence = {
        "source_url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "http_status": status_code,
        "html": html,
    }

    soup = BeautifulSoup(html, "html.parser")
    plans = []
    for card in soup.select(".plan"):
        name = card.select_one(".plan-name")
        price = card.select_one(".price")
        period = card.select_one(".period")
        if not name or not price:
            continue

        raw_price = price.get_text(strip=True)
        amount, currency = parse_price(raw_price)
        plans.append(
            {
                "plan": name.get_text(strip=True),
                "raw_price": raw_price,
                "amount": amount,
                "currency": currency,
                "period": parse_period(period.get_text(strip=True)) if period else None,
                "status": "ok" if amount is not None else "price_unavailable",
            }
        )
    return plans, evidence


if __name__ == "__main__":
    plans, evidence = extract_prices("http://127.0.0.1:5001/pricing")
    print("Evidence:", {k: v for k, v in evidence.items() if k != "html"})
    print()
    for p in plans:
        print(p)
