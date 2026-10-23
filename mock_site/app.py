from flask import Flask, redirect, render_template_string

app = Flask(__name__)

# 10 fake competitors. Prices are in USD. Some bill monthly, some yearly, and
# they use different tier names (Basic / Professional / Team ...) on purpose,
# so the agent has to normalise them.
COMPETITORS = {
    "acmesoft":  {"name": "AcmeSoft",  "period": "monthly", "plans": [("Starter", 9),    ("Pro", 29),          ("Business", 79)]},
    "betasoft":  {"name": "BetaSoft",  "period": "monthly", "plans": [("Basic", 12),      ("Professional", 39), ("Team", 99)]},
    "cloudnine": {"name": "CloudNine", "period": "yearly",  "plans": [("Lite", 108),     ("Plus", 348),        ("Enterprise", 948)]},
    "datadash":  {"name": "DataDash",  "period": "monthly", "plans": [("Starter", 15),    ("Pro", 45),          ("Business", 120)]},
    "evergreen": {"name": "Evergreen", "period": "yearly",  "plans": [("Basic", 120),    ("Pro", 384),         ("Team", 1080)]},
    "fluxhq":    {"name": "FluxHQ",    "period": "monthly", "plans": [("Lite", 8),        ("Plus", 25),         ("Business", 70)]},
    "gridly":    {"name": "Gridly",    "period": "monthly", "plans": [("Starter", 10),    ("Professional", 32), ("Enterprise", 90)]},
    "hivework":  {"name": "HiveWork",  "period": "yearly",  "plans": [("Starter", 96),   ("Pro", 300),         ("Business", 840)]},
    "ironleaf":  {"name": "IronLeaf",  "period": "monthly", "plans": [("Basic", 14),      ("Pro", 42),          ("Team", 110)]},
    "jetstack":  {"name": "JetStack",  "period": "monthly", "plans": [("Starter", 11),    ("Plus", 35),         ("Business", 95)]},
}

MODES = {
    "normal": "Normal",
    "price_changed": "TC1 price +20%",
    "inr": "TC2 USD->INR",
    "contact_sales": "TC3 Contact sales",
}

# The scenario each competitor is currently showing (resets on restart)
modes = {slug: "normal" for slug in COMPETITORS}


def money(symbol, amount):
    return f"{symbol}{round(amount):,}"


def plans_for(slug):
    c = COMPETITORS[slug]
    mode = modes[slug]
    period_text = "per month" if c["period"] == "monthly" else "per year"
    out = []
    for i, (name, amount) in enumerate(c["plans"]):
        if mode == "inr":
            out.append((name, money("₹", amount * 83), period_text))
        elif mode == "contact_sales" and i == 1:
            out.append((name, "Contact sales", ""))
        elif mode == "price_changed" and i == 1:
            out.append((name, money("$", amount * 1.2), period_text))
        else:
            out.append((name, money("$", amount), period_text))
    return out


PRICING_PAGE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{ company }} Pricing</title>
  <style>
    body { font-family: Arial, sans-serif; background:#f5f6fa; margin:0; padding:40px; }
    h1 { text-align:center; }
    .plans { display:flex; gap:24px; justify-content:center; margin-top:30px; }
    .plan { background:white; border-radius:12px; padding:28px; width:220px;
            text-align:center; box-shadow:0 2px 8px rgba(0,0,0,.1); }
    .price { font-size:34px; font-weight:bold; color:#2d3a8c; }
    .period { color:#777; }
  </style>
</head>
<body>
  <h1>{{ company }} Pricing</h1>
  <div class="plans">
    {% for name, price, period in plans %}
    <div class="plan" data-plan="{{ name }}">
      <h2 class="plan-name">{{ name }}</h2>
      <div class="price">{{ price }}</div>
      <div class="period">{{ period }}</div>
    </div>
    {% endfor %}
  </div>
</body>
</html>
"""

CONTROL_PAGE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Mock Competitors Control Panel</title>
  <style>
    body { font-family: Arial, sans-serif; max-width:900px; margin:30px auto; }
    table { border-collapse:collapse; width:100%; }
    td, th { padding:8px 10px; border-bottom:1px solid #ddd; text-align:left; }
    a.b { display:inline-block; padding:6px 10px; margin:2px; background:#2d3a8c; color:white;
          text-decoration:none; border-radius:6px; font-size:13px; }
    a.on { background:#1b8a3a; }
    a.reset { background:#b33; }
  </style>
</head>
<body>
  <h1>Mock Competitors: Control Panel</h1>
  <p>Each row is one fake competitor. Click a scenario, then open (or refresh) its pricing page.
     <a class="b reset" href="/reset">Reset all to Normal</a></p>
  <table>
    <tr><th>Competitor</th><th>Scenario</th><th>Page</th></tr>
    {% for slug, c in competitors.items() %}
    <tr>
      <td>{{ c.name }}</td>
      <td>
        {% for key, label in modes_list.items() %}
          <a class="b {{ 'on' if modes[slug] == key else '' }}" href="/set/{{ slug }}/{{ key }}">{{ label }}</a>
        {% endfor %}
      </td>
      <td><a href="/c/{{ slug }}/pricing" target="_blank">open</a></td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>
"""


@app.route("/")
def control():
    return render_template_string(
        CONTROL_PAGE, competitors=COMPETITORS, modes_list=MODES, modes=modes
    )


@app.route("/set/<slug>/<mode>")
def set_mode(slug, mode):
    if slug in COMPETITORS and mode in MODES:
        modes[slug] = mode
    return redirect("/")


@app.route("/reset")
def reset():
    for slug in modes:
        modes[slug] = "normal"
    return redirect("/")


@app.route("/c/<slug>/pricing")
def pricing(slug):
    if slug not in COMPETITORS:
        return "Unknown competitor", 404
    return render_template_string(
        PRICING_PAGE, company=COMPETITORS[slug]["name"], plans=plans_for(slug)
    )


# Old single-competitor URLs from earlier steps still work (they control AcmeSoft)
@app.route("/pricing")
def pricing_legacy():
    return pricing("acmesoft")


@app.route("/set/<mode>")
def set_mode_legacy(mode):
    return set_mode("acmesoft", mode)


if __name__ == "__main__":
    app.run(port=5001, debug=True)
v
